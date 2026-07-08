"""Compute scope protocol."""


from __future__ import annotations

from datetime import tzinfo
from typing import LiteralString, Protocol

__all__: tuple[LiteralString, ...] = ("ComputeScope",)


class ComputeScope(Protocol):
    scope_name: str

    @property
    def local_tz(self) -> tzinfo: ...
