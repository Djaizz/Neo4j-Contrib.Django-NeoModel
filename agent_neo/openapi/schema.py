"""Custom schema class for drf-spectacular to handle DjangoField from django-neomodel."""


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
        # Handle DjangoField from django-neomodel
        if isinstance(model_field, DjangoField):
            # Return a string schema for DjangoField
            return build_basic_type(OpenApiTypes.STR)

        # If it's not a models.Field, return string schema (don't call parent)
        if not isinstance(model_field, models.Field):
            return build_basic_type(OpenApiTypes.STR)

        # For regular Django fields, use the parent implementation
        return super()._map_model_field(model_field, direction)
