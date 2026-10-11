"""NodeSets answer Django's changelist total-ordering probe: not total, so `-pk` is appended."""


from __future__ import annotations

from neomodel.sync_.match import NodeSet

import django_neomodel  # noqa: F401  (importing the package installs the answer)
from tests.someapp.models import Book


def test_every_nodeset_reports_its_ordering_as_not_total() -> None:
    assert NodeSet.totally_ordered is False
    assert Book.objects.totally_ordered is False


def test_an_ordered_nodeset_answers_too() -> None:
    assert Book.objects.order_by("title").totally_ordered is False
