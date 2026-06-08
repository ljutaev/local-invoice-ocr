import hashlib
from pathlib import Path

from invoiceflow import crypto, store
from invoiceflow.config import Settings


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _ingest_bytes(settings: Settings, source: str, source_ref: str, data: bytes) -> int | None:
    digest = _sha256(data)
    if store.find_job_by_hash(digest) is not None:
        return None  # duplicate
    enc_path = settings.store_dir / f"{digest}.bin"
    enc_path.write_bytes(crypto.encrypt(data))
    return store.create_job(source, source_ref, digest, str(enc_path))


class FolderSource:
    def __init__(self, settings: Settings):
        self.settings = settings

    @staticmethod
    def hash_file(path: Path) -> str:
        return _sha256(Path(path).read_bytes())

    def ingest_file(self, path: Path) -> int | None:
        path = Path(path)
        return _ingest_bytes(self.settings, "folder", str(path), path.read_bytes())


class UploadSource:
    def __init__(self, settings: Settings):
        self.settings = settings

    def ingest_bytes(self, data: bytes, filename: str) -> int | None:
        return _ingest_bytes(self.settings, "upload", filename, data)
