"""An append-only, tamper-evident decision log.

Each record carries the hash of the record before it, so the log is a chain. A
record altered after the fact breaks every hash downstream of it, and
verify_chain finds the first break rather than merely reporting that something
is wrong.

That property is what makes the trail evidence rather than a log file. A dispute
turns on whether the record was written before the payment or edited after it,
and an append-only file alone cannot answer that.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from ..core.hashing import content_hash
from .records import AuditRecord

GENESIS = "sha256:" + "0" * 64


class AuditLog:
    """Append-only JSONL. One record per line, chained by hash."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def __len__(self) -> int:
        return sum(1 for _ in self.read_all())

    def head(self) -> tuple[int, str]:
        """The sequence number and hash to chain the next record onto."""
        sequence, previous = -1, GENESIS
        for record in self.read_all():
            sequence, previous = record.sequence, content_hash(record)
        return sequence + 1, previous

    def append(self, record: AuditRecord) -> AuditRecord:
        """Write a record, filling in its place in the chain."""
        sequence, previous = self.head()
        chained = record.model_copy(update={"sequence": sequence, "previous_hash": previous})
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(chained.model_dump_json() + "\n")
        return chained

    def read_all(self) -> Iterator[AuditRecord]:
        if not self.path.exists():
            return
        with self.path.open(encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    yield AuditRecord.model_validate_json(line)

    def verify_chain(self) -> int | None:
        """Return the sequence number of the first broken link, or None if intact."""
        expected_previous = GENESIS
        for index, record in enumerate(self.read_all()):
            if record.previous_hash != expected_previous or record.sequence != index:
                return record.sequence
            expected_previous = content_hash(record)
        return None
