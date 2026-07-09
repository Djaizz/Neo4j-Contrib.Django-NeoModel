"""NeoModel base, datetime coercion helpers, and optional drf-spectacular schema support."""


from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone, tzinfo as _tzinfo_base
from typing import Any, LiteralString

from django_neomodel import DjangoNode as DjangoNeoModel
from neomodel.properties import DateTimeNeo4jFormatProperty, DateTimeProperty, Property


__all__: tuple[LiteralString, ...] = (
    "DjangoNeoModelWithCreatedAndUpdatedProps",
    "apply_neo4j_datetime_coercion_patch",
    "coerce_to_fixed_offset_for_neo4j",
    "DjangoNeoModelAutoSchema",  # noqa: F822 — lazy export via __getattr__
)


class _ZoneNamePreservingTzInfo(_tzinfo_base):
    """A tzinfo that preserves the named zone (e.g. ``Asia/Kolkata``) while
    using a pre-computed UTC offset, so the Neo4j driver's
    ``DateTime._utc_offset`` (which calls ``tzinfo.utcoffset(neo4j_datetime)``
    and crashes in CPython's ``_zoneinfo`` C extension for ``ZoneInfo``) never
    touches ``_zoneinfo``.

    The Neo4j Bolt encoder (``dehydrate_datetime``) checks ``hasattr(tz, "key")``
    and, if present, sends a Structure ``b"i"`` with the zone name — preserving
    the named timezone in Neo4j's ZonedDateTime (not just the offset).
    """

    __slots__ = ("_key", "_offset", "_dst")

    def __init__(self, key: str, offset: timedelta) -> None:
        self._key = key
        self._offset = offset
        self._dst = timedelta(0)

    @property
    def key(self) -> str:
        return self._key

    def utcoffset(self, dt: Any | None = None) -> timedelta | None:
        return self._offset

    def tzname(self, dt: Any | None = None) -> str | None:
        return self._key

    def dst(self, dt: Any | None = None) -> timedelta | None:
        return self._dst

    def __repr__(self) -> str:
        return f"_ZoneNamePreservingTzInfo({self._key!r})"


def coerce_to_fixed_offset_for_neo4j(value: Any) -> Any:
    """Coerce ``zoneinfo.ZoneInfo`` / ``pytz`` tzinfos to a crash-safe wrapper
    that **preserves the named timezone** for Neo4j's ZonedDateTime.

    The Neo4j Python driver's ``DateTime._utc_offset`` calls
    ``tzinfo.utcoffset(neo4j_datetime)`` — passing a *neo4j* DateTime (not a
    Python ``datetime``). CPython 3.13/3.14's ``_zoneinfo`` C extension crashes
    (SIGSEGV) when ``ZoneInfo.utcoffset()`` receives a non-``datetime`` argument.

    This helper:
    1. Pre-computes the UTC offset from the **Python** datetime (safe — Python
       ``datetime`` works fine with ``ZoneInfo.utcoffset()``).
    2. Extracts the zone name (``ZoneInfo.key`` or ``pytz.tzinfo.zone``).
    3. Returns a datetime with a :class:`_ZoneNamePreservingTzInfo` that carries
       both the zone name (``.key``) and the pre-computed offset (``.utcoffset()``),
       so the Neo4j driver can serialize it as a named-zone ZonedDateTime
       (Bolt Structure ``b"i"``) without touching ``_zoneinfo``.

    For tzinfos without a zone name (e.g. plain ``timezone(offset)``), the
    original value is returned unchanged (the driver sends offset-only Bolt
    Structure ``b"I"``).
    """
    if value is None or not isinstance(value, datetime):
        return value
    tz = value.tzinfo
    if tz is None or isinstance(tz, timezone):
        return value  # naive or already fixed-offset — driver handles these natively
    offset = value.utcoffset()
    if offset is None:
        return value
    # Extract the zone name from ZoneInfo (.key) or pytz (.zone)
    zone_key = getattr(tz, "key", None) or getattr(tz, "zone", None)
    if zone_key and isinstance(zone_key, str):
        return value.replace(tzinfo=_ZoneNamePreservingTzInfo(zone_key, offset))
    # No zone name available — fall back to fixed-offset (offset-only in Neo4j)
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
