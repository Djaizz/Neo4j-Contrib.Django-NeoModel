"""Compute scope protocol."""
from __future__ import annotations
from datetime import tzinfo
from typing import Protocol

class ComputeScope(Protocol):
    scope_name: str
    @property
    def local_tz(self) -> tzinfo: ...
