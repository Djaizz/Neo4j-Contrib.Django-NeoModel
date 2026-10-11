"""A fresh root ``NodeSet`` per request, for Django REST framework viewsets over neomodel.

A viewset's class-level ``queryset: NodeSet = X.objects`` is ONE mutable object
created at class-definition time. neomodel's ``NodeSet.filter`` and
``order_by`` mutate it in place and return ``self``, and DRF's
``GenericAPIView.get_queryset`` clones only Django ``QuerySet`` instances — a
``NodeSet`` is handed to every request as-is. So every filter, ordering and
detail-route narrowing from request N would accumulate onto the object request
N+1 received: the second name a client asked for would resolve against a
queryset still constricted to the first (a healthy entity 404s), and an
unfiltered list would carry the previous request's ``?name=`` narrowing
forever.

One definition gives every viewset the same discipline — cross-cutting cost in
a free function taking the surface as an argument, not in a base class.
"""


from __future__ import annotations

from typing import TYPE_CHECKING, LiteralString

from neomodel.sync_.match import NodeSet

if TYPE_CHECKING:
    from rest_framework.generics import GenericAPIView


__all__: tuple[LiteralString, ...] = ("fresh_root_queryset",)


def fresh_root_queryset(viewset: GenericAPIView, /) -> NodeSet:
    """Return a NEW ``NodeSet`` over the viewset's model — never the class attribute.

    ``Model.objects`` constructs a fresh ``NodeSet`` on every access (verified
    against the pinned neomodel); the class attribute captured one at import.
    The class attribute stays where it is — DRF's router and schema read it —
    but nothing per-request may mutate it.
    """
    queryset = viewset.queryset
    assert isinstance(queryset, NodeSet)
    return queryset.model.objects
