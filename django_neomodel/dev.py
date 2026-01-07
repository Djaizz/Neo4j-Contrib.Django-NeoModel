"""Django-NeoModel Integration Utilities.

This module provides base classes and utilities for integrating Django Admin with NeoModel (Neo4j OGM).
It consolidates common patterns needed to make Django Admin work with NeoModel nodes.
"""


from abc import abstractmethod

from django_neomodel import DjangoField, DjangoNode


__all__ = ['DjangoNeoNode']


# Get the metaclass of DjangoNode to combine with ABCMeta
_DjangoNodeMeta = type(DjangoNode)


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


class DjangoNeoNode(DjangoNode):
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
        return super().full_clean(exclude=exclude, validate_unique=validate_unique)

    def validate_constraints(self, exclude=None):
        """Override validate_constraints to satisfy Django Admin's expectations.

        Django Admin's ModelForm calls validate_constraints() on the model instance,
        but NeoModel's DjangoNode doesn't have this method. This override provides
        a no-op implementation since NeoModel doesn't have Django ORM constraints.

        Args:
            exclude: Fields to exclude from constraint validation (ignored)
        """
        # NeoModel doesn't have Django ORM constraints, so this is a no-op
