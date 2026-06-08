from email.message import EmailMessage

from invoiceflow import email_source, store


def _email_with_attachments() -> bytes:
    msg = EmailMessage()
    msg["From"] = "vendor@example.com"
    msg["To"] = "me@example.com"
    msg["Subject"] = "Invoice"
    msg.set_content("See attached.")
    msg.add_attachment(b"%PDF-1.4 inv", maintype="application", subtype="pdf",
                       filename="invoice.pdf")
    msg.add_attachment(b"hello", maintype="text", subtype="plain", filename="note.txt")
    return msg.as_bytes()


def test_extract_attachments_only_invoice_types():
    atts = email_source.extract_attachments(_email_with_attachments())
    names = [fn for fn, _ in atts]
    assert names == ["invoice.pdf"]            # .txt excluded
    assert atts[0][1] == b"%PDF-1.4 inv"


def test_ingest_attachments_creates_email_jobs(db, settings):
    jids = email_source.ingest_attachments(settings, [("a.pdf", b"%PDF-1.4 x")])
    assert len(jids) == 1
    from invoiceflow import ingest
    job = store.find_job_by_hash(ingest._sha256(b"%PDF-1.4 x"))
    assert job.source == "email"
