"""Regression tests for SmartCrusher's Rust->Python CCR mirror bridge.

The bridge (_mirror_single_hash_to_python_store) copies a Rust-stored CCR
entry into the Python compression_store so /v1/retrieve can resolve
`<<ccr:HASH>>` markers that are already committed to the prompt by the time
this runs. A failure here silently orphans that marker (permanent 404 on
retrieval) even though the Rust store still has the bytes — so it must
retry transient failures and log loudly (not at debug) when it gives up,
instead of swallowing the failure silently.
"""

from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest

from headroom.transforms.smart_crusher import SmartCrusher


class _FlakyStore:
    """Fails `n_failures` times, then succeeds."""

    def __init__(self, n_failures: int) -> None:
        self.n_failures = n_failures
        self.calls = 0
        self.stored: dict | None = None

    def store(self, **kwargs):
        self.calls += 1
        if self.calls <= self.n_failures:
            raise RuntimeError("transient backend hiccup")
        self.stored = kwargs
        return kwargs.get("explicit_hash")


@pytest.fixture
def crusher() -> SmartCrusher:
    return SmartCrusher()


def test_mirror_retries_once_and_succeeds(monkeypatch, crusher, caplog) -> None:
    """First attempt fails transiently, second succeeds -> no warning, data mirrored."""
    monkeypatch.setattr(crusher, "_rust", SimpleNamespace(ccr_get=lambda h: "ORIGINAL_CANONICAL_JSON"))
    flaky = _FlakyStore(n_failures=1)
    monkeypatch.setattr(
        "headroom.cache.compression_store.get_compression_store", lambda: flaky
    )

    with caplog.at_level(logging.WARNING):
        crusher._mirror_single_hash_to_python_store(
            "abc123def456", strategy="smart_crusher", query_context="", tool_name=None
        )

    assert flaky.calls == 2
    assert flaky.stored is not None
    assert flaky.stored["original"] == "ORIGINAL_CANONICAL_JSON"
    assert flaky.stored["explicit_hash"] == "abc123def456"
    assert not any("failed to mirror hash" in r.message for r in caplog.records)


def test_mirror_persistent_failure_logs_warning_not_debug(monkeypatch, crusher, caplog) -> None:
    """Both attempts fail -> loud WARNING (previously silent at debug level)."""
    monkeypatch.setattr(crusher, "_rust", SimpleNamespace(ccr_get=lambda h: "ORIGINAL_CANONICAL_JSON"))
    always_flaky = _FlakyStore(n_failures=999)
    monkeypatch.setattr(
        "headroom.cache.compression_store.get_compression_store", lambda: always_flaky
    )

    with caplog.at_level(logging.WARNING):
        crusher._mirror_single_hash_to_python_store(
            "deadbeef0011", strategy="smart_crusher", query_context="", tool_name=None
        )

    assert always_flaky.calls == 2  # exactly one retry, not an infinite loop
    warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert any("failed to mirror hash" in r.message for r in warnings)
    assert any("deadbeef0011" in r.message for r in warnings)


def test_mirror_malformed_hash_does_not_retry(monkeypatch, crusher, caplog) -> None:
    """explicit_hash ValueError is not transient -> single attempt, no retry."""
    monkeypatch.setattr(crusher, "_rust", SimpleNamespace(ccr_get=lambda h: "ORIGINAL_CANONICAL_JSON"))

    class _RejectingStore:
        def __init__(self) -> None:
            self.calls = 0

        def store(self, **kwargs):
            self.calls += 1
            raise ValueError("explicit_hash must be a non-empty hex string")

    rejecting = _RejectingStore()
    monkeypatch.setattr(
        "headroom.cache.compression_store.get_compression_store", lambda: rejecting
    )

    with caplog.at_level(logging.WARNING):
        crusher._mirror_single_hash_to_python_store(
            "not-a-real-hash", strategy="smart_crusher", query_context="", tool_name=None
        )

    assert rejecting.calls == 1
    assert any("invalid hash" in r.message for r in caplog.records)
