"""fresh_root_queryset hands each request a new NodeSet, never the viewset's class attribute."""


from __future__ import annotations

import pytest
from neomodel.sync_.match import NodeSet

from django_neomodel.util.fresh_queryset import fresh_root_queryset
from tests.someapp.models import Book


class _BookViewSet:
    queryset = Book.objects


def test_a_new_nodeset_over_the_viewset_model() -> None:
    viewset = _BookViewSet()
    first = fresh_root_queryset(viewset)
    second = fresh_root_queryset(viewset)
    assert isinstance(first, NodeSet)
    assert first is not _BookViewSet.queryset
    assert first is not second
    assert first.model is Book


def test_refuses_a_queryset_that_is_not_a_nodeset() -> None:
    viewset = type("ViewSet", (), {"queryset": []})()
    with pytest.raises(AssertionError):
        fresh_root_queryset(viewset)
