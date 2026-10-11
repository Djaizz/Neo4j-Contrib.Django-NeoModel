"""Datetimes the Neo4j driver can serialize, zone names kept; the deflate patch."""


from __future__ import annotations

from datetime import datetime, timedelta, timezone, tzinfo as _tzinfo_base
from typing import Any, LiteralString

from neomodel.properties import DateTimeNeo4jFormatProperty


__all__: tuple[LiteralString, ...] = (
    "apply_neo4j_datetime_coercion_patch",
    "coerce_to_fixed_offset_for_neo4j",
)


class _ZoneNamePreservingTzInfo(_tzinfo_base):
    """A tzinfo that preserves the named zone (e.g. ``Asia/Kathmandu``) while
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
