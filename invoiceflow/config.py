import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    base_dir: Path
    inbox_dir: Path
    store_dir: Path          # encrypted originals
    db_path: Path
    ollama_url: str
    model: str
    ocr_lang: str
    text_threshold: int      # min chars/page to treat PDF as digital
    max_attempts: int


def get_settings(base: str | None = None) -> Settings:
    base_dir = Path(base or os.environ.get("INVOICEFLOW_HOME", "~/.invoiceflow")).expanduser()
    return Settings(
        base_dir=base_dir,
        inbox_dir=base_dir / "inbox",
        store_dir=base_dir / "store",
        db_path=base_dir / "invoiceflow.db",
        ollama_url=os.environ.get("OLLAMA_URL", "http://localhost:11434"),
        model=os.environ.get("INVOICEFLOW_MODEL", "qwen2.5:14b"),
        ocr_lang=os.environ.get("INVOICEFLOW_OCR_LANG", "eng"),
        text_threshold=int(os.environ.get("INVOICEFLOW_TEXT_THRESHOLD", "100")),
        max_attempts=int(os.environ.get("INVOICEFLOW_MAX_ATTEMPTS", "3")),
    )


def ensure_dirs(s: Settings) -> None:
    for d in (s.base_dir, s.inbox_dir, s.store_dir):
        d.mkdir(parents=True, exist_ok=True)
