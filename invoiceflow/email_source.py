import email
import imaplib

from invoiceflow import ingest
from invoiceflow.config import Settings

_EXT = (".pdf", ".png", ".jpg", ".jpeg")


def extract_attachments(raw: bytes) -> list[tuple[str, bytes]]:
    """Pull invoice-like attachments (pdf/image) out of a raw RFC822 message."""
    msg = email.message_from_bytes(raw)
    out: list[tuple[str, bytes]] = []
    for part in msg.walk():
        fn = part.get_filename()
        if fn and fn.lower().endswith(_EXT):
            payload = part.get_payload(decode=True)
            if payload:
                out.append((fn, payload))
    return out


def ingest_attachments(settings: Settings, attachments) -> list[int]:
    jids = []
    for fn, data in attachments:
        jid = ingest._ingest_bytes(settings, "email", fn, data)
        if jid:
            jids.append(jid)
    return jids


class EmailSource:
    def __init__(self, settings: Settings):
        self.settings = settings

    def fetch_new(self) -> list[int]:
        s = self.settings
        M = imaplib.IMAP4_SSL(s.imap_host)
        M.login(s.imap_user, s.imap_pass)
        M.select(s.imap_folder)
        _, data = M.search(None, "UNSEEN")
        jids: list[int] = []
        for num in data[0].split():
            _, msgdata = M.fetch(num, "(RFC822)")
            raw = msgdata[0][1]
            jids += ingest_attachments(s, extract_attachments(raw))
            M.store(num, "+FLAGS", "\\Seen")
        M.logout()
        return jids
