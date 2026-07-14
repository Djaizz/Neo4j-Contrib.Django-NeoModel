"""Analytical-product scope protocol (the minimal compute-scope surface)."""


from __future__ import annotations

from datetime import tzinfo
from typing import Protocol, runtime_checkable


__all__ = ("AnalyticalProductScope",)


@runtime_checkable
class AnalyticalProductScope(Protocol):
    """Minimal scope surface for analytical-product computation.

    Carries the facility/scope identifier (``scope_name``) and the
    facility-local timezone (``local_tz``, aliased as ``tz``).
    """

    scope_name: str

    @property
    def local_tz(self) -> tzinfo: ...

    @property
    def tz(self) -> tzinfo:
        """Alias for :attr:`local_tz`."""
        return self.local_tz

