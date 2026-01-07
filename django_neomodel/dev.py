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
    - `objects` descriptor: Alias for `nodes` to provide Django-like API

    This is an abstract base class and should not have its own label in the database.
    """
    __abstract_node__ = True  # Prevent DjangoNeoNode from being included in label hierarchy

    # Class-level descriptor that provides Django-like 'objects' API
    # Usage: Model.objects.all() instead of Model.nodes.all()
    objects = _ObjectsDescriptor()
