"""A prefetch that never ran is distinguishable from a value that is absent.

The four `format_prefetched_*` helpers read `admin_or_viewset._prefetch_cache`
through `getattr(..., {})`, so a missing cache produced an empty dict and every
helper returned its default. "The prefetch did not run" and "this node has no
value" were the same observable outcome, and `format_prefetched_count_display`
returned `0` — a plausible business answer rather than an obvious fault.

`strict=True` separates them. The default stays `False`, so this guards the opt-in
rather than a behaviour change forced on existing callers.
"""


from __future__ import annotations

from typing import Any

import pytest

from agent_neo.util.django_neomodel.admin.prefetch import (
    PrefetchNotRunError,
    format_prefetched_count_display,
    format_prefetched_list_display,
    format_prefetched_list_display_truncated,
    format_prefetched_scalar_display,
)


class _Node:
    """A node carrying no prefetched attributes."""


class _ViewsetWithoutPrefetch:
    """The state that used to be silent: the prefetch never ran."""


class _ViewsetWithPrefetch:
    def __init__(self, cache: dict[Any, dict[str, Any]]) -> None:
        self._prefetch_cache = cache


_HELPERS = (
    format_prefetched_scalar_display,
    format_prefetched_list_display,
    format_prefetched_list_display_truncated,
    format_prefetched_count_display,
)


@pytest.mark.parametrize('helper', _HELPERS, ids=lambda h: h.__name__)
def test_a_missing_prefetch_cache_raises_under_strict(helper) -> None:
    with pytest.raises(PrefetchNotRunError, match='prefetch did not run'):
        helper(
            _Node(),
            admin_or_viewset=_ViewsetWithoutPrefetch(),
            node_key='k',
            attr_name='_prefetched_x',
            cache_entry_key='x',
            strict=True,
        )


@pytest.mark.parametrize('helper', _HELPERS, ids=lambda h: h.__name__)
def test_a_missing_prefetch_cache_is_still_tolerated_by_default(helper) -> None:
    """The default is unchanged, deliberately: strict is opt-in."""
    assert helper(
        _Node(),
        admin_or_viewset=_ViewsetWithoutPrefetch(),
        node_key='k',
        attr_name='_prefetched_x',
        cache_entry_key='x',
    ) in ('-', 0)


@pytest.mark.parametrize('helper', _HELPERS, ids=lambda h: h.__name__)
def test_a_present_cache_missing_this_key_does_not_raise_under_strict(helper) -> None:
    """Strict distinguishes "no prefetch" from "no value" — it does not conflate them.

    The cache ran and simply has nothing for this node. That is a real answer, and
    strict must not turn it into an error, or it would just move the silence.
    """
    viewset = _ViewsetWithPrefetch({'other': {'x': 'v'}})
    assert helper(
        _Node(),
        admin_or_viewset=viewset,
        node_key='k',
        attr_name='_prefetched_x',
        cache_entry_key='x',
        strict=True,
    ) in ('-', 0)


def test_the_count_helper_no_longer_answers_zero_when_nothing_ran() -> None:
    """The sharpest case: `0` is indistinguishable from a true zero."""
    assert format_prefetched_count_display(
        _Node(), admin_or_viewset=_ViewsetWithoutPrefetch(),
        node_key='k', attr_name='_prefetched_xs', cache_entry_key='xs',
    ) == 0
    with pytest.raises(PrefetchNotRunError):
        format_prefetched_count_display(
            _Node(), admin_or_viewset=_ViewsetWithoutPrefetch(),
            node_key='k', attr_name='_prefetched_xs', cache_entry_key='xs',
            strict=True,
        )


def test_values_are_read_from_the_node_before_the_cache() -> None:
    node = _Node()
    node._prefetched_x = 'from-node'
    assert format_prefetched_scalar_display(
        node, admin_or_viewset=_ViewsetWithPrefetch({'k': {'x': 'from-cache'}}),
        node_key='k', attr_name='_prefetched_x', cache_entry_key='x',
    ) == 'from-node'


def test_values_fall_back_to_the_cache_when_the_node_has_none() -> None:
    assert format_prefetched_scalar_display(
        _Node(), admin_or_viewset=_ViewsetWithPrefetch({'k': {'x': 'from-cache'}}),
        node_key='k', attr_name='_prefetched_x', cache_entry_key='x',
    ) == 'from-cache'


@pytest.mark.parametrize('helper', _HELPERS, ids=lambda h: h.__name__)
def test_only_the_node_may_be_passed_positionally(helper) -> None:
    """HFCODB-0024 D2: `attr_name` and `cache_entry_key` are adjacent same-typed
    strings, and a transposition used to fail silently to the default. The
    signature is what rules that out."""
    with pytest.raises(TypeError):
        helper(_Node(), _ViewsetWithPrefetch({}), 'k', '_prefetched_x', 'x')
