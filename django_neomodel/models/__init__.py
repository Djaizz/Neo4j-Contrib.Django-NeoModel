"""Abstract DjangoNode bases for an application's node classes.

Django imports this package whenever ``django_neomodel`` is in ``INSTALLED_APPS``.
Everything here is abstract, so importing it registers no node label.
"""


from __future__ import annotations

from typing import LiteralString

from .base import DjangoNeoModelWithCreatedAndUpdatedProps


__all__: tuple[LiteralString, ...] = ("DjangoNeoModelWithCreatedAndUpdatedProps",)
