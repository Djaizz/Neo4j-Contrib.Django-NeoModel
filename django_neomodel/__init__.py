from __future__ import annotations

from dataclasses import dataclass, field
from functools import total_ordering

from django.db.models import signals
from django.db.models.fields import BLANK_CHOICE_DASH
from django.conf import settings
from django.forms import fields as form_fields
from django.db.models.options import Options
from django.core.exceptions import ValidationError

from neomodel import RequiredProperty, DeflateError, StructuredNode, UniqueIdProperty
from neomodel.sync_.node import NodeMeta
from neomodel.sync_.match import NodeSet


__author__ = "Robin Edwards"
__email__ = "robin.ge@gmail.com"
__license__ = "MIT"
__package__ = "django_neomodel"
__version__ = "0.2.0"


default_app_config = "django_neomodel.apps.NeomodelConfig"


def classproperty(f):
    class cpf(object):
        def __init__(self, getter):
            self.getter = getter

        def __get__(self, obj, type=None):
            return self.getter(type)

    return cpf(f)


@total_ordering
class DjangoField(object):
    """
    Fake Django model field object which wraps a neomodel Property
    """

    is_relation = False
    concrete = True
    editable = True
    creation_counter = 0
    unique = False
    primary_key = False
    auto_created = False
    empty_values = [None, '']  # Django's display_for_field expects field.empty_values

    def __init__(self, prop, name):
        self.prop = prop

        self.name = name
        self.remote_field = name
        self.attname = name
        self.verbose_name = name
        self.help_text = getattr(prop, "help_text", "")

        if isinstance(prop, UniqueIdProperty):
            # this seems that can be implemented in neomodel
            # django-neomodel does have the needed code already but neomodel does not support
            prop.primary_key = True

        self.primary_key = getattr(prop, "primary_key", False)
        self.label = prop.label if prop.label else name

        form_cls = getattr(prop, "form_field_class", "Field")  # get field string
        self.form_class = getattr(form_fields, form_cls, form_fields.CharField)

        self._has_default = prop.has_default
        self.required = prop.required
        self.blank = not self.required
        self.choices = getattr(prop, "choices", None)

        self.creation_counter = DjangoField.creation_counter
        DjangoField.creation_counter += 1

    def __eq__(self, other):
        # Needed for @total_ordering
        if isinstance(other, DjangoField):
            return self.creation_counter == other.creation_counter
        return NotImplemented

    def __lt__(self, other):
        # This is needed because bisect does not take a comparison function.
        if isinstance(other, DjangoField):
            return self.creation_counter < other.creation_counter
        return NotImplemented

    def has_default(self):
        return self._has_default

    def save_form_data(self, instance, data):
        setattr(instance, self.name, data)

    def value_from_object(self, instance):
        return getattr(instance, self.name)

    def formfield(self, **kwargs):
        """
        Returns a django.forms.Field instance for this database Property.

        """
        defaults = {
            "required": self.required,
            "label": self.label or self.name,
            "help_text": self.help_text,
        }

        if self.has_default():
            defaults["initial"] = self.prop.default_value()

        if self.choices:
            # Fields with choices get special treatment.
            include_blank = not self.required or not (
                self.has_default() or "initial" in kwargs
            )
            defaults["choices"] = self.get_choices(include_blank=include_blank)
            defaults["coerce"] = self.to_python

            # Many of the subclass-specific formfield arguments (min_value,
            # max_value) don't apply for choice fields, so be sure to only pass
            # the values that TypedChoiceField will understand.
            for k in list(kwargs):
                if k not in (
                    "coerce",
                    "empty_value",
                    "choices",
                    "required",
                    "widget",
                    "label",
                    "initial",
                    "help_text",
                    "error_messages",
                    "show_hidden_initial",
                ):
                    del kwargs[k]

        defaults.update(kwargs)

        return self.form_class(**defaults)

    def to_python(self, value):
        return value

    def get_choices(self, include_blank=True):
        blank_defined = False
        blank_choice = BLANK_CHOICE_DASH
        choices = list(self.choices) if self.choices else []

        if issubclass(type(self.choices), dict):
            choices = list(enumerate(self.choices))

        for choice, __ in choices:
            if choice in ("", None):
                blank_defined = True
                break

        first_choice = blank_choice if include_blank and not blank_defined else []
        return first_choice + choices


# patch NodeSet with `.query` to make it compatible with Django Admin expectations
@dataclass
class Query:
    """Query object for Django Admin compatibility with NeoModel NodeSets."""
    select_related: bool = False
    order_by: list[str] = field(default_factory=lambda: ["pk"])


NodeSet.query = Query()


class NeoManager:
    def __init__(self, model):
        self.model = model

    def get_queryset(self):
        return NodeSet(source=self.model)


class MetaClass(NodeMeta):
    def __new__(cls, *args, **kwargs):
        super_new = super().__new__
        new_cls = super_new(cls, *args, **kwargs)
        setattr(new_cls, "_default_manager", NeoManager(new_cls))
        return new_cls


class _ObjectsDescriptor:
    """Descriptor that provides Django-like 'objects' API for NeoModel nodes.

    This allows classes to use Model.objects.all() instead of Model.nodes.all(),
    making the API more Django-like for admin classes.

    This is an internal implementation detail and should not be used directly.
    """

    def __get__(self, obj, cls=None):
        """Return the 'nodes' manager when accessed as a class attribute."""
        if cls is None:
            cls = type(obj)
        return cls.nodes


class DjangoNode(StructuredNode, metaclass=MetaClass):
    __abstract_node__ = True

    # Class-level descriptor that provides Django-like 'objects' API
    # Usage: Model.objects.all() instead of Model.nodes.all()
    objects = _ObjectsDescriptor()

    @classproperty
    def _meta(self):
        if hasattr(self.Meta, "unique_together"):
            raise NotImplementedError(
                "unique_together property not supported by neomodel"
            )

        opts = Options(self.Meta, app_label=self.Meta.app_label)
        opts.contribute_to_class(self, self.__name__)

        # Note: _default_manager is set by MetaClass, not here

        # Find the primary key field name
        pk_field_name = None
        for key, prop in self.__all_properties__:
            opts.add_field(DjangoField(prop, key), getattr(prop, "private", False))
            if getattr(prop, "primary_key", False):
                pk_field_name = key
                # Store the property for Django Admin compatibility
                setattr(self, '_pk_property', prop)
                prop.auto_created = True

        # Create a proper pk property that returns the actual value
        if pk_field_name:
            # Use a closure to capture the field name
            field_name = pk_field_name

            def pk_getter(instance):
                """Return the primary key value for this instance."""
                return getattr(instance, field_name, None)

            # Create a custom property descriptor that supports the 'name' attribute
            # (Python's built-in property doesn't allow setting arbitrary attributes)
            class PkProperty(property):
                """Custom property descriptor that supports a 'name' attribute."""
                def __init__(self, fget, name):
                    super().__init__(fget)
                    self.name = name

            pk_prop = PkProperty(pk_getter, pk_field_name)
            setattr(self, 'pk', pk_prop)

        return opts

    def full_clean(self, exclude=None, validate_unique=False, validate_constraints=True):
        """
        Validate node, on error raising ValidationErrors which can be handled by django forms

        :param exclude: Fields to exclude from validation
        :param validate_unique: Check if conflicting node exists in the labels indexes
        :param validate_constraints: Ignored (Django ORM-specific, NeoModel doesn't have Django ORM constraints)
        :return:
        """

        # validate against neomodel
        try:
            self.deflate(self.__properties__, self)
        except DeflateError as e:
            raise ValidationError({e.property_name: e.msg})
        except RequiredProperty as e:
            raise ValidationError({e.property_name: "is required"})

        # Note: validate_constraints is ignored since NeoModel doesn't have Django ORM constraints

    def validate_unique(self, exclude):
        # get unique indexed properties
        unique_props = []
        for k, p in self.__class__.defined_properties(
            aliases=False, rels=False
        ).items():
            if k not in exclude and p.unique_index:
                unique_props.append(k)
        cls = self.__class__

        props = self.__properties__

        # see if any nodes already exist with each property
        for key in unique_props:
            if key == "pk" and getattr(self.__class__, key).auto_created:
                continue
            val = getattr(self.__class__, key).deflate(props[key])
            node = cls.nodes.get_or_none(**{key: val})

            # if exists and not this node
            if node and node.element_id != getattr(self, "element_id", None):
                raise ValidationError({key, "already exists"})

    def pre_save(self):
        if getattr(settings, "NEOMODEL_SIGNALS", True):
            self._creating_node = getattr(self, "element_id", None) is None
            signals.pre_save.send(sender=self.__class__, instance=self)

    def post_save(self):
        if getattr(settings, "NEOMODEL_SIGNALS", True):
            created = self._creating_node
            delattr(self, "_creating_node")
            signals.post_save.send(
                sender=self.__class__, instance=self, created=created
            )

    def pre_delete(self):
        if getattr(settings, "NEOMODEL_SIGNALS", True):
            signals.pre_delete.send(sender=self.__class__, instance=self)

    def post_delete(self):
        if getattr(settings, "NEOMODEL_SIGNALS", True):
            signals.post_delete.send(sender=self.__class__, instance=self)

    def serializable_value(self, attr):
        """Return serializable value for a field, handling None attributes."""
        # Django Admin sometimes calls serializable_value with attr=None
        if attr is None:
            return None
        return str(getattr(self, attr))

    def validate_constraints(self, exclude=None):
        """Override validate_constraints to satisfy Django Admin's expectations.

        Django Admin's ModelForm calls validate_constraints() on the model instance,
        but NeoModel's DjangoNode doesn't have this method. This override provides
        a no-op implementation since NeoModel doesn't have Django ORM constraints.

        Args:
            exclude: Fields to exclude from constraint validation (ignored)
        """
        # NeoModel doesn't have Django ORM constraints, so this is a no-op
