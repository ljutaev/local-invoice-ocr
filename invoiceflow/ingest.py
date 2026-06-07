import hashlib
from pathlib import Path

from invoiceflow import crypto, store
from invoiceflow.config import Settings


class FolderSource:
    def __init__(self, settings: Settings):
        self.settings = settings

    @staticmethod
    def hash_file(path: Path) -> str:
        h = hashlib.sha256()
        h.update(Path(path).read_bytes())
        return h.hexdigest()

    def ingest_file(self, path: Path) -> int | None:
        path = Path(path)
        digest = self.hash_file(path)
        if store.find_job_by_hash(digest) is not None:
            return None  # duplicate
        enc_path = self.settings.store_dir / f"{digest}.bin"
        enc_path.write_bytes(crypto.encrypt(path.read_bytes()))
        return store.create_job("folder", str(path), digest, str(enc_path))
