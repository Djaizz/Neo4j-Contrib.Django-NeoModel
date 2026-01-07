"""Django-NeoModel Integration Utilities.

This module provides base classes and utilities for integrating Django Admin with NeoModel (Neo4j OGM).
It consolidates common patterns needed to make Django Admin work with NeoModel nodes.
"""


from django_neomodel import DjangoField, DjangoNode


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
