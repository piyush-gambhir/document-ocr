"""Request-scoped recovery budget parsing and expiry."""
import time

import pytest

from core.recovery_budget import (BUDGET_ENV, DEFAULT_BUDGET_SECONDS, configured_budget,
                                  recovery_allowed, recovery_deadline)


@pytest.mark.parametrize('raw, expected', [
    ('', DEFAULT_BUDGET_SECONDS), ('2.5', 2.5), ('0', 0.0), ('-1', 0.0),
    ('off', None), ('OFF', None), ('fast', DEFAULT_BUDGET_SECONDS),
])
def test_configured_budget(raw, expected):
    assert configured_budget(raw) == expected


def test_no_limit_outside_a_scan():
    assert recovery_allowed()


def test_deadline_applies_only_inside_its_scan(monkeypatch):
    monkeypatch.setenv(BUDGET_ENV, '1')
    with recovery_deadline(time.monotonic() - 2):
        assert not recovery_allowed()
    assert recovery_allowed()
    with recovery_deadline(time.monotonic()):
        assert recovery_allowed()


def test_off_never_expires(monkeypatch):
    monkeypatch.setenv(BUDGET_ENV, 'off')
    with recovery_deadline(time.monotonic() - 3600):
        assert recovery_allowed()
