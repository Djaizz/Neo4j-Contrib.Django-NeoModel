"""Django-NeoModel Integration Utilities.

This module provides base classes and utilities for integrating Django Admin with NeoModel (Neo4j OGM).
It consolidates common patterns needed to make Django Admin work with NeoModel nodes.
"""

import logging

from abc import ABC, ABCMeta, abstractmethod

from django.contrib.admin import ModelAdmin
from django.contrib.admin.views.main import ChangeList
from django_neomodel import DjangoField, DjangoNode

logger = logging.getLogger(__name__)

# Get the metaclass of DjangoNode to combine with ABCMeta
_DjangoNodeMeta = type(DjangoNode)


class _DjangoNeoNodeMeta(_DjangoNodeMeta, ABCMeta):
    """Combined metaclass for DjangoNeoNode.

    This metaclass combines the metaclass of DjangoNode (from NeoModel) with ABCMeta
    to allow DjangoNeoNode to inherit from both DjangoNode and ABC without metaclass conflicts.
    """
    pass

# ============================================================================
# Monkey-patches for Django-NeoModel compatibility
# ============================================================================

# Monkey-patch DjangoField to add empty_values attribute for Django conventions
# Django's display_for_field expects field.empty_values, but DjangoField doesn't have it
if not hasattr(DjangoField, 'empty_values'):
    DjangoField.empty_values = [None, '']

# Monkey-patch DjangoNode.serializable_value to handle None attributes
# Django Admin sometimes calls serializable_value with attr=None, which causes TypeError
if not hasattr(DjangoNode.serializable_value, '_patched_for_neomodel'):
    _original_serializable_value = DjangoNode.serializable_value

    def patched_serializable_value(self, field_name):
        """Override serializable_value to handle None field names."""
        if field_name is None:
            return None
        return _original_serializable_value(self, field_name)

    setattr(patched_serializable_value, '_patched_for_neomodel', True)
    DjangoNode.serializable_value = patched_serializable_value


# ============================================================================
# Base Classes
# ============================================================================

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


class DjangoNeoNode(DjangoNode, ABC, metaclass=_DjangoNeoNodeMeta):
    """Base class for NeoModel nodes that work with Django Admin.

    This class provides fundamental adaptations from Django ORM to NeoModel:
    - `pk` property: Abstract property that each subclass must implement to return its unique identifier
    - `objects` descriptor: Alias for `nodes` to provide Django-like API
    - `_pk_field_name` class attribute: Each subclass must set this to the field name used for pk queries

    This is an abstract base class and should not have its own label in the database.
    """
    __abstract_node__ = True  # Prevent DjangoNeoNode from being included in label hierarchy

    # Class-level descriptor that provides Django-like 'objects' API
    # Usage: Model.objects.all() instead of Model.nodes.all()
    objects = _ObjectsDescriptor()

    # Each subclass must set this to the field name used for primary key queries
    # (e.g., 'uri', 'name', 'label')
    _pk_field_name: str = None

    @property
    @abstractmethod
    def pk(self):
        """Return the unique identifier for this node as pk to adapt NeoModel to Django conventions.

        Each subclass must implement this property to return its preferred unique identifier
        (e.g., uri for schema classes, name for instantiation classes).

        NeoModel doesn't allow querying by element_id (it's an internal identifier),
        so each class must use its own unique field.
        """
        raise NotImplementedError("Subclasses must implement pk property")

    def __str__(self) -> str:
        """Default string representation using pk property.

        Subclasses can override if they need a different string representation.
        """
        return str(self.pk)

    def full_clean(self, exclude=None, validate_unique=True, validate_constraints=True):
        """Override full_clean to accept Django ORM parameters that NeoModel doesn't support.

        Django Admin's ModelForm calls full_clean() with validate_unique and validate_constraints
        parameters, but NeoModel's DjangoNode.full_clean() doesn't accept these parameters.
        This override accepts them but ignores them, since NeoModel doesn't have Django ORM
        constraints or unique validation in the same way.

        Args:
            exclude: Fields to exclude from validation (passed to parent)
            validate_unique: Ignored (Django ORM-specific)
            validate_constraints: Ignored (Django ORM-specific)
        """
        # Call parent full_clean with only the exclude parameter
        # NeoModel's full_clean doesn't support validate_unique or validate_constraints
        return super().full_clean(exclude=exclude)

    def validate_constraints(self, exclude=None):
        """Override validate_constraints to satisfy Django Admin's expectations.

        Django Admin's ModelForm calls validate_constraints() on the model instance,
        but NeoModel's DjangoNode doesn't have this method. This override provides
        a no-op implementation since NeoModel doesn't have Django ORM constraints.

        Args:
            exclude: Fields to exclude from constraint validation (ignored)
        """
        # NeoModel doesn't have Django ORM constraints, so this is a no-op
        pass


class DjangoNeoField(DjangoField):
    """Base class for NeoModel fields that work with Django Admin.

    This class extends DjangoField but doesn't add any functionality yet.
    It serves as a placeholder for future Django Admin-specific enhancements.
    """


class ListQuerysetWrapper(list):
    """A wrapper around a list to mimic Django QuerySet methods.

    This is used when NeoModel NodeSets are converted to lists, but Django Admin
    still expects methods like .count(), ._clone(), and .model attribute.
    """
    def __init__(self, items, model=None):
        """Initialize wrapper with items and optional model reference.

        Args:
            items: List of items to wrap
            model: The model class (used for .model attribute)
        """
        super().__init__(items)
        self._model = model

    @property
    def model(self):
        """Return the model class for Django conventions."""
        return self._model

    def count(self):
        return len(self)

    def _clone(self):
        # Return a new instance with a shallow copy of items, mimicking QuerySet._clone()
        return ListQuerysetWrapper(list(self), model=self._model)

    def filter(self, *args, **kwargs):
        # For simplicity, this wrapper does not implement full filtering.
        # The actual filtering should happen at the NeoModel NodeSet level.
        # If Django Admin tries to filter this list, it means the get_queryset
        # in ChangeList or ModelAdmin was not correctly overridden.
        logger.warning("Attempted to call .filter() on ListQuerysetWrapper. "
                       "Ensure filtering is done on the NeoModel NodeSet.")
        return self # Return self to allow chaining, but no actual filtering occurs


class NoPkChangeList(ChangeList):
    """Custom ChangeList that prevents Django from using 'pk' for NeoModel nodes.

    Django Admin expects Django ORM models with a `pk` field, but NeoModel nodes
    don't have a Django ORM primary key. This ChangeList handles all the edge cases
    that arise from this mismatch.
    """

    def __init__(self, request, model, list_display, list_display_links,
                 list_filter, date_hierarchy, search_fields, list_select_related,
                 list_per_page, list_max_show_all, list_editable, model_admin, sortable_by, search_help_text):
        """Override to handle NeoModel nodes that don't have a Django ORM primary key."""
        try:
            logger.info(f"Initializing ChangeList for {model.__name__}")

            # NeoModel nodes don't have a Django ORM primary key field
            # Create a mock pk object to prevent Django from failing when accessing lookup_opts.pk.attname
            class MockPk:
                attname = None

            # Temporarily set lookup_opts.pk if it's None
            original_pk = None
            if hasattr(model._meta, 'pk') and model._meta.pk is None:
                original_pk = model._meta.pk
                model._meta.pk = MockPk()

            try:
                super().__init__(
                    request, model, list_display, list_display_links,
                    list_filter, date_hierarchy, search_fields, list_select_related,
                    list_per_page, list_max_show_all, list_editable, model_admin, sortable_by, search_help_text
                )

                # Set pk_attname to None since NeoModel nodes don't have a pk field
                self.pk_attname = None

                logger.info(f"ChangeList initialized successfully for {model.__name__}")
            finally:
                # Restore original pk if we modified it
                if original_pk is not None:
                    model._meta.pk = original_pk
        except Exception as e:
            logger.error(f"Exception in ChangeList.__init__ for {model.__name__}: {e}", exc_info=True, stack_info=True)
            raise

    def get_queryset(self, request):
        """Override to prevent Django Admin from applying Django ORM filters to NeoModel queryset.

        Django Admin's default get_queryset tries to apply list_filter using Django ORM's .filter(),
        which doesn't work with NeoModel NodeSets. We bypass that and use the queryset from
        the ModelAdmin's get_queryset method directly.
        """
        try:
            # Call the ModelAdmin's get_queryset directly, which should return a NodeSet
            qs = self.model_admin.get_queryset(request)
            logger.debug(f"ChangeList.get_queryset returning queryset from ModelAdmin: {type(qs)}")
            return qs
        except Exception as e:
            logger.error(f"Exception in NoPkChangeList.get_queryset for {self.model.__name__}: {e}", exc_info=True, stack_info=True)
            raise

    def _get_deterministic_ordering(self, ordering):
        """Override to prevent Django from appending 'pk' to ordering."""
        # Filter out 'pk' and '-pk' from ordering
        filtered_ordering = tuple(o for o in ordering if o not in ('pk', '-pk'))
        # Ensure we have at least one ordering field
        if not filtered_ordering:
            # Fall back to the model admin's default ordering
            model_ordering = self.model_admin.ordering or ()
            if model_ordering:
                filtered_ordering = model_ordering
        return filtered_ordering

    def url_for_result(self, result):
        """Override to handle NeoModel nodes that use pk property instead of pk_attname.

        Django Admin's url_for_result uses getattr(result, self.pk_attname), but
        when pk_attname is None (for NeoModel nodes), we need to use the pk property instead.
        Temporarily set pk_attname to 'pk' so the parent method works.
        """
        original_pk_attname = self.pk_attname
        self.pk_attname = 'pk'  # Temporarily set to 'pk' to use the property on NeoModel nodes
        try:
            url = super().url_for_result(result)
        finally:
            self.pk_attname = original_pk_attname  # Restore original
        return url

    def get_results(self, request):
        """Override to handle NeoModel NodeSets that may be converted to lists.

        Django Admin's get_results() expects a queryset with .count() and ._clone() methods.
        If root_queryset or queryset is a list (converted from NodeSet), we need to handle it differently.
        """
        try:
            logger.info(f"Getting results for ChangeList: {self.model.__name__}")
            logger.debug(f"root_queryset type: {type(self.root_queryset)}, queryset type: {type(self.queryset)}")

            # Check if root_queryset or queryset is a list and wrap if needed
            original_root_queryset = self.root_queryset
            original_queryset = self.queryset
            wrapped_root = isinstance(self.root_queryset, list)
            wrapped_queryset = isinstance(self.queryset, list)

            if wrapped_root:
                self.root_queryset = ListQuerysetWrapper(self.root_queryset, model=self.model)
            if wrapped_queryset:
                self.queryset = ListQuerysetWrapper(self.queryset, model=self.model)

            try:
                result = super().get_results(request)
                logger.info(f"Results retrieved successfully for {self.model.__name__}")
                return result
            finally:
                # Restore originals
                self.root_queryset = original_root_queryset
                self.queryset = original_queryset
        except Exception as e:
            logger.error(f"Exception in ChangeList.get_results for {self.model.__name__}: {e}", exc_info=True, stack_info=True)
            raise


class DjangoNeoModelAdmin(ModelAdmin):
    """Base ModelAdmin class for NeoModel nodes.

    This class provides all the necessary overrides to make Django Admin work with NeoModel nodes.
    Subclasses should:
    1. Set `list_display`, `search_fields`, and `ordering` attributes
    2. Optionally override `get_queryset` if custom queryset logic is needed (default uses `self.model.objects.all()`)
    3. Optionally override `get_search_results` if custom search logic is needed

    The default `get_queryset` implementation uses `self.model.objects.all()` which is an alias
    for `self.model.nodes.all()` via the `DjangoNeoNode.objects` descriptor.
    """

    def changelist_view(self, request, extra_context=None):
        """Override to catch and log exceptions before Django Admin's error handling."""
        try:
            return super().changelist_view(request, extra_context)
        except Exception as e:
            logger.error(f"Exception in {self.__class__.__name__}.changelist_view: {e}", exc_info=True, stack_info=True)
            raise

    def get_changelist(self, request, **kwargs):
        """Override to use custom ChangeList that prevents 'pk' ordering."""
        return NoPkChangeList

    def has_add_permission(self, request):
        """Override to prevent Django from checking database table existence."""
        return True

    def has_change_permission(self, request, obj=None):
        """Override to prevent Django from checking database table existence."""
        return True

    def has_delete_permission(self, request, obj=None):
        """Override to prevent Django from checking database table existence."""
        return True

    def get_queryset(self, request):
        """Override to return clean queryset without Django Q objects.

        Default implementation uses self.model.objects.all() (which is an alias for nodes.all()).
        Subclasses can override if custom queryset logic is needed.

        Note: This returns a NeoModel NodeSet, which may be converted to a list later.
        If Django Admin needs a .model attribute, it should be handled in get_object override.
        """
        # Use objects.all() which is an alias for nodes.all() via DjangoNeoNode.objects descriptor
        queryset = self.model.objects.all()
        # If queryset is a list (already converted), wrap it with model attribute
        if isinstance(queryset, list):
            return ListQuerysetWrapper(queryset, model=self.model)
        # For NodeSets, add model attribute if it doesn't exist
        if not hasattr(queryset, 'model'):
            queryset.model = self.model
        return queryset

    def get_object(self, request, object_id, from_field=None):
        """Override to handle NeoModel nodes that use custom unique identifiers as pk.

        Django Admin's default get_object expects a queryset with a .model attribute,
        but NeoModel NodeSets don't have that. This override directly queries the
        NeoModel node by the class's _pk_field_name (e.g., uri, name, label).

        Note: NeoModel doesn't allow querying by element_id (it's an internal identifier),
        so we use the class's _pk_field_name attribute to determine which field to query.
        """
        try:
            # Get the pk field name from the model class
            pk_field_name = getattr(self.model, '_pk_field_name', None)
            if not pk_field_name:
                raise ValueError(f"{self.model.__name__} must set _pk_field_name class attribute (e.g., 'uri', 'name', 'label')")

            # object_id is the pk value (e.g., uri, name, label for NeoModel nodes)
            # Query directly using NeoModel's get method with the pk field
            obj = self.model.objects.get(**{pk_field_name: object_id})
            return obj
        except (self.model.DoesNotExist, Exception) as e:
            # NeoModel may raise DoesNotExist or other exceptions
            # Check if it's a "not found" type exception
            if 'not found' in str(e).lower() or 'does not exist' in str(e).lower():
                from django.http import Http404
                raise Http404(f"{self.model._meta.verbose_name} with pk={object_id} does not exist.")
            # For other exceptions, log and re-raise
            logger.error(f"Exception in {self.__class__.__name__}.get_object for {self.model.__name__}: {e}", exc_info=True, stack_info=True)
            raise

    def get_search_results(self, request, queryset, search_term):
        """Override to handle search using neomodel filters instead of Django Q objects.

        This default implementation handles search across all fields in `search_fields` using
        NeoModel's Q objects with OR logic. Subclasses can override for custom search behavior.
        """
        if search_term and self.search_fields:
            from neomodel.match_q import Q as NeoQ
            q_objects = []
            for field in self.search_fields:
                q_objects.append(NeoQ(**{f"{field}__icontains": search_term}))
            # Combine with OR
            if q_objects:
                combined_q = q_objects[0]
                for q_obj in q_objects[1:]:
                    combined_q = combined_q | q_obj
                queryset = queryset.filter(combined_q)
        return queryset, False  # False = no distinct needed for NeoModel


# ============================================================================
# Public API Exports
# ============================================================================

__all__ = [
    'DjangoNeoNode',
    'DjangoNeoField',
    'DjangoNeoModelAdmin',
    'NoPkChangeList',
]

