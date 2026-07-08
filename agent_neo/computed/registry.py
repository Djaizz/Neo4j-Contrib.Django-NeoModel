"""Registered computed/design node classes."""
from __future__ import annotations
_REGISTERED_COMPUTED_NODE_CLASSES: list[type] = []
_REGISTERED_DESIGN_NODE_CLASSES: list[type] = []
_EXTRA_RELATIONSHIP_TARGET_RESOLVERS: dict[str, type] = {}

def register_computed_node_class(node_class: type) -> None:
    if node_class not in _REGISTERED_COMPUTED_NODE_CLASSES:
        _REGISTERED_COMPUTED_NODE_CLASSES.append(node_class)

def register_design_node_class(node_class: type) -> None:
    if node_class not in _REGISTERED_DESIGN_NODE_CLASSES:
        _REGISTERED_DESIGN_NODE_CLASSES.append(node_class)

def register_relationship_target_class(class_name: str, node_class: type) -> None:
    _EXTRA_RELATIONSHIP_TARGET_RESOLVERS[class_name] = node_class

def iter_registered_computed_node_classes() -> list[type]:
    return list(_REGISTERED_COMPUTED_NODE_CLASSES)

def iter_registered_design_node_classes() -> list[type]:
    return list(_REGISTERED_DESIGN_NODE_CLASSES)
