"""OpenAPI schemas for DjangoNode models: a drf-spectacular ``AutoSchema``.

``DjangoNeoModelAutoSchema`` maps each ``DjangoField`` to a string schema. Needs
the optional ``drf-spectacular`` dependency.
"""


from __future__ import annotations

from typing import LiteralString

from django.db import models
from django_neomodel import DjangoField
from drf_spectacular.openapi import AutoSchema
from drf_spectacular.plumbing import build_basic_type
from drf_spectacular.types import OpenApiTypes


__all__: tuple[LiteralString, ...] = ("DjangoNeoModelAutoSchema",)


class DjangoNeoModelAutoSchema(AutoSchema):
    """
    Custom AutoSchema that handles DjangoField from django-neomodel.

    When drf-spectacular tries to introspect DjangoField (which is not a
    django.db.models.Field), it raises an AssertionError. This class
    catches that and returns a string schema instead.
    """

    def _map_model_field(self, model_field, direction):
        if isinstance(model_field, DjangoField):
            return build_basic_type(OpenApiTypes.STR)

        if not isinstance(model_field, models.Field):
            return build_basic_type(OpenApiTypes.STR)

        return super()._map_model_field(model_field, direction)
