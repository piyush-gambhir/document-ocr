"""Request-scoped time budget for optional recovery OCR passes.

Recovery re-reads damaged rows after the base passes have run. Each re-read is
optional, so a scan stops starting new ones once the budget measured from the
start of the scan is spent, and returns the best evidence it already has. A
pass that has started always finishes; the budget bounds when passes may begin.

    DOCUMENT_OCR_RECOVERY_BUDGET_SECONDS=5   # default; 0 disables recovery
    DOCUMENT_OCR_RECOVERY_BUDGET_SECONDS=off # no limit
"""
from __future__ import annotations

import contextvars
import logging
import os
import time
from contextlib import contextmanager
from typing import Iterator, Optional

logger = logging.getLogger("document-ocr.recovery_budget")

BUDGET_ENV = "DOCUMENT_OCR_RECOVERY_BUDGET_SECONDS"
DEFAULT_BUDGET_SECONDS = 5.0

_deadline: contextvars.ContextVar[Optional[float]] = contextvars.ContextVar(
    "document_ocr_recovery_deadline", default=None)


def configured_budget(raw: Optional[str] = None) -> Optional[float]:
    """Seconds allowed from scan start, or None for no limit."""
    value = (os.getenv(BUDGET_ENV) if raw is None else raw) or ""
    value = value.strip().lower()
    if not value:
        return DEFAULT_BUDGET_SECONDS
    if value in {"off", "none", "unlimited"}:
        return None
    try:
        seconds = float(value)
    except ValueError:
        # A typo in deployment config must not fail every scan.
        logger.warning("%s=%r is not a number of seconds or 'off'; using %s",
                       BUDGET_ENV, value, DEFAULT_BUDGET_SECONDS)
        return DEFAULT_BUDGET_SECONDS
    return max(seconds, 0.0)


@contextmanager
def recovery_deadline(start: float) -> Iterator[None]:
    """Bound optional recovery for the scan that began at ``start`` (monotonic).

    A nested call inside an active scan keeps the outer deadline.
    """
    if _deadline.get() is not None:
        yield
        return
    budget = configured_budget()
    token = _deadline.set(None if budget is None else start + budget)
    try:
        yield
    finally:
        _deadline.reset(token)


def recovery_allowed() -> bool:
    """True while an optional recovery pass may still start."""
    deadline = _deadline.get()
    return deadline is None or time.monotonic() < deadline
