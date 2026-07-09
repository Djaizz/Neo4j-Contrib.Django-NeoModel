"""Signal-driven trigger for dependency-aware cascade (mark-only, never recompute inline)."""


from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any, LiteralString
import logging

from agent_neo.analytical_product.enum import NodeLifecycleStatus


__all__: tuple[LiteralString, ...] = (
    'build_cascade_change_handler',
    'connect_cascade_signals',
    'is_retired_lifecycle_change',
    'register_cascade_signals_once',
)


log = logging.getLogger(__name__)

_REGISTERED_ONCE: bool = False


def is_retired_lifecycle_change(instance: Any) -> bool:
    """Whether this node's current state should propagate to dependents."""
    lifecycle_status = getattr(instance, 'lifecycle_status', None)
    return lifecycle_status == NodeLifecycleStatus.RETIRED.value


def build_cascade_change_handler(
    *,
    mark_impacted_needs_redo: Callable[..., None],
    is_cascade_suppressed: Callable[[], bool],
    is_cascade_relevant_change: Callable[[Any], bool] | None = None,
) -> Callable[..., None]:
    """Build a Django signal receiver that marks dependents when upstream nodes retire."""

    def on_analytical_product_change(sender: type, instance: Any, **kwargs: Any) -> None:
        if is_cascade_suppressed():
            return
        relevance_check = is_cascade_relevant_change or is_retired_lifecycle_change
        if not relevance_check(instance):
            return
        element_id = getattr(instance, 'element_id', None)
        if element_id is None:
            return
        try:
            mark_impacted_needs_redo(changed_element_ids=[element_id])
        except Exception as exc:  # noqa: BLE001 - marking failure must never break the originating save
            log.warning('cascade mark on %s change failed: %s', getattr(sender, '__name__', sender), exc)

    return on_analytical_product_change


def connect_cascade_signals(
    senders: Iterable[type],
    *,
    mark_impacted_needs_redo: Callable[..., None],
    is_cascade_suppressed: Callable[[], bool],
    dispatch_uid_prefix: str,
    is_cascade_relevant_change: Callable[[Any], bool] | None = None,
) -> int:
    """Connect mark-only cascade receivers; returns number of senders connected."""
    from django.db.models.signals import post_delete, post_save

    receiver = build_cascade_change_handler(
        mark_impacted_needs_redo=mark_impacted_needs_redo,
        is_cascade_suppressed=is_cascade_suppressed,
        is_cascade_relevant_change=is_cascade_relevant_change,
    )
    connected = 0
    for sender in senders:
        post_save.connect(
            receiver=receiver,
            sender=sender,
            weak=True,
            dispatch_uid=f'{dispatch_uid_prefix}_post_save_{sender.__name__}',
            apps=None,
        )
        post_delete.connect(
            receiver=receiver,
            sender=sender,
            weak=True,
            dispatch_uid=f'{dispatch_uid_prefix}_post_delete_{sender.__name__}',
            apps=None,
        )
        connected += 1
    return connected


def register_cascade_signals_once(
    senders: Iterable[type],
    *,
    mark_impacted_needs_redo: Callable[..., None],
    is_cascade_suppressed: Callable[[], bool],
    dispatch_uid_prefix: str,
    is_cascade_relevant_change: Callable[[Any], bool] | None = None,
) -> int:
    """Idempotent wrapper around ``connect_cascade_signals`` for Django ``AppConfig.ready``."""
    global _REGISTERED_ONCE
    if _REGISTERED_ONCE:
        return 0
    connected = connect_cascade_signals(
        senders,
        mark_impacted_needs_redo=mark_impacted_needs_redo,
        is_cascade_suppressed=is_cascade_suppressed,
        dispatch_uid_prefix=dispatch_uid_prefix,
        is_cascade_relevant_change=is_cascade_relevant_change,
    )
    _REGISTERED_ONCE = True
    log.debug('cascade signals connected once for %d senders', connected)
    return connected
