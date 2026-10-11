"""Abstract node bases for DjangoNode models."""


from __future__ import annotations

from datetime import UTC, datetime
from typing import LiteralString

from django_neomodel import DjangoNode as DjangoNeoModel
from neomodel.properties import DateTimeProperty, Property


__all__: tuple[LiteralString, ...] = ("DjangoNeoModelWithCreatedAndUpdatedProps",)


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
