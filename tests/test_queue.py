from invoiceflow import store, queue
from invoiceflow.models import PROCESSING
from invoiceflow.db import SessionLocal
from invoiceflow.models import Job


def test_claim_returns_pending_then_none(db):
    j1 = store.create_job("folder", "a", "h1", "/e1")
    j2 = store.create_job("folder", "b", "h2", "/e2")
    claimed = [queue.claim_next_job("w1"), queue.claim_next_job("w1")]
    assert set(claimed) == {j1, j2}
    assert queue.claim_next_job("w1") is None  # nothing left pending


def test_claimed_job_marked_processing(db):
    jid = store.create_job("folder", "a", "h1", "/e1")
    queue.claim_next_job("w1")
    with SessionLocal() as s:
        assert s.get(Job, jid).status == PROCESSING
