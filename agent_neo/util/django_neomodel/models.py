"""NeoModel base, datetime coercion helpers, and optional drf-spectacular schema support."""


from __future__ import annotations

from datetime import UTC, datetime, timezone
from typing import Any, LiteralString

from django_neomodel import DjangoNode as DjangoNeoModel
from neomodel.properties import DateTimeNeo4jFormatProperty, DateTimeProperty, Property


__all__: tuple[LiteralString, ...] = (
    "DjangoNeoModelWithCreatedAndUpdatedProps",
    "apply_neo4j_datetime_coercion_patch",
    "coerce_to_fixed_offset_for_neo4j",
    "DjangoNeoModelAutoSchema",  # noqa: F822 — lazy export via __getattr__
)


def coerce_to_fixed_offset_for_neo4j(value: Any) -> Any:
    """Coerce zoneinfo datetimes to fixed-offset tz before Neo4j driver serialization."""
    if value is None or not isinstance(value, datetime):
        return value
    tz = value.tzinfo
    if tz is None:
        return value
    offset = value.utcoffset()
    if offset is None or isinstance(tz, timezone):
        return value
    return value.astimezone(timezone(offset))


_orig_neo4j_datetime_deflate = DateTimeNeo4jFormatProperty.deflate


def _neo4j_datetime_deflate_coerced(self: DateTimeNeo4jFormatProperty, value: Any) -> Any:  # type: ignore[override]
    return _orig_neo4j_datetime_deflate(self, coerce_to_fixed_offset_for_neo4j(value))


def apply_neo4j_datetime_coercion_patch() -> None:
    """Apply Neo4j datetime coercion patch (call explicitly at startup if needed)."""
    if getattr(DateTimeNeo4jFormatProperty.deflate, "__name__", "") != "_neo4j_datetime_deflate_coerced":
        DateTimeNeo4jFormatProperty.deflate = _neo4j_datetime_deflate_coerced  # type: ignore[assignment]


class DjangoNeoModelWithCreatedAndUpdatedProps(DjangoNeoModel):
    """Abstract NeoModel base with automatic ``created`` / ``updated`` audit stamps."""

    __abstract_node__: bool = True

    created: Property = DateTimeProperty(
        default_now=True,
        unique_index=False,
        index=False,
        fulltext_index=None,
        vector_index=None,
        required=False,
        db_property=None,
        label="Created at",
        help_text="Created at",
    )
    updated: Property = DateTimeProperty(
        default_now=True,
        unique_index=False,
        index=False,
        fulltext_index=None,
        vector_index=None,
        required=False,
        db_property=None,
        label="Last Updated at",
        help_text="Last Updated at",
    )

    class Meta:
        abstract: bool = True

    def save(self, *args, **kwargs):
        if not hasattr(self, "created") or getattr(self, "created", None) is None:
            self.created = datetime.now(tz=UTC)
        self.updated = datetime.now(tz=UTC)
        return super().save(*args, **kwargs)


def __getattr__(name: str) -> Any:
    if name == "DjangoNeoModelAutoSchema":
        from django.db import models
        from django_neomodel import DjangoField
        from drf_spectacular.openapi import AutoSchema
        from drf_spectacular.plumbing import build_basic_type
        from drf_spectacular.types import OpenApiTypes

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

        globals()["DjangoNeoModelAutoSchema"] = DjangoNeoModelAutoSchema
        return DjangoNeoModelAutoSchema

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
