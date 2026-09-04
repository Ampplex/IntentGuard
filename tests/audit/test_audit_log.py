"""The trail has to be evidence, which means tampering has to be detectable."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from intentguard.audit import GENESIS, AuditLog, AuditRecord
from intentguard.core import LatencyBreakdown, Outcome, from_rupees

AT = datetime(2026, 9, 4, 10, 0, tzinfo=UTC)


def a_record(offer_id: str = "off_1") -> AuditRecord:
    return AuditRecord(
        record_id=f"aud_{offer_id}",
        sequence=0,
        previous_hash="",
        intent_id="int_1",
        offer_id=offer_id,
        mandate_hash="sha256:aa",
        offer_hash="sha256:bb",
        decision=Outcome.BLOCK,
        checked_total_paise=from_rupees(5200),
        max_total_paise=from_rupees(5000),
        latency_ms=LatencyBreakdown(),
        checked_at=AT,
    )


@pytest.fixture
def log(tmp_path):
    return AuditLog(tmp_path / "audit.jsonl")


def test_the_first_record_chains_to_genesis(log) -> None:
    written = log.append(a_record())
    assert written.sequence == 0
    assert written.previous_hash == GENESIS


def test_records_chain_in_order(log) -> None:
    for index in range(5):
        written = log.append(a_record(f"off_{index}"))
        assert written.sequence == index
    assert len(log) == 5
    assert log.verify_chain() is None


def test_an_edited_record_breaks_the_chain(log) -> None:
    """The point of the whole structure. A dispute turns on whether the record
    was written before the payment or edited after it."""
    for index in range(4):
        log.append(a_record(f"off_{index}"))
    assert log.verify_chain() is None

    lines = log.path.read_text(encoding="utf-8").splitlines()
    tampered = json.loads(lines[1])
    tampered["decision"] = "ALLOW"
    tampered["checked_total_paise"] = 1
    lines[1] = json.dumps(tampered)
    log.path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    assert log.verify_chain() == 2, "the break shows at the record after the edit"


def test_a_deleted_record_breaks_the_chain(log) -> None:
    for index in range(4):
        log.append(a_record(f"off_{index}"))
    lines = log.path.read_text(encoding="utf-8").splitlines()
    del lines[1]
    log.path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    assert log.verify_chain() is not None


def test_records_survive_a_round_trip(log) -> None:
    log.append(a_record())
    revived = next(iter(log.read_all()))
    assert revived.checked_total_paise == from_rupees(5200)
    assert isinstance(revived.checked_total_paise, int)


def test_an_empty_log_is_intact(log) -> None:
    assert log.verify_chain() is None
    assert len(log) == 0
