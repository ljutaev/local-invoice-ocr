from datetime import datetime, timezone

from sqlalchemy import text

from invoiceflow.db import get_engine
from invoiceflow.models import PENDING, PROCESSING


def claim_next_job(worker_id: str) -> int | None:
    """Atomically claim the oldest pending job. Returns job id or None.

    The single UPDATE ... (SELECT ... LIMIT 1) ... RETURNING is atomic; under
    SQLite WAL only one writer proceeds at a time, so concurrent workers cannot
    claim the same row. No explicit BEGIN IMMEDIATE needed (engine.begin()
    already opens the transaction).
    """
    now = datetime.now(timezone.utc).isoformat()
    with get_engine().begin() as conn:
        row = conn.execute(
            text(
                "UPDATE jobs SET status=:proc, worker_id=:w, started_at=:t "
                "WHERE id = (SELECT id FROM jobs WHERE status=:pend "
                "ORDER BY created_at LIMIT 1) RETURNING id"
            ),
            {"proc": PROCESSING, "w": worker_id, "t": now, "pend": PENDING},
        ).fetchone()
    return row[0] if row else None
