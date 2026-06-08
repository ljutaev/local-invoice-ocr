from dataclasses import dataclass, field

import fitz  # PyMuPDF
import pytesseract
from PIL import Image

from invoiceflow.config import Settings

RENDER_DPI = 150
_ZOOM = RENDER_DPI / 72.0  # PDF points → pixels at RENDER_DPI


@dataclass
class Page:
    text: str
    width: int = 0
    height: int = 0
    # word boxes in pixel coords at RENDER_DPI: [{"t","x0","y0","x1","y1"}]
    words: list = field(default_factory=list)


@dataclass
class ReaderResult:
    pages: list
    full_text: str
    used_ocr: bool


def _filetype(filename: str) -> str | None:
    return "pdf" if filename.lower().endswith(".pdf") else None


def _ocr_page(pix: "fitz.Pixmap", lang: str) -> tuple[str, list]:
    """Return (text, word-boxes[px]) from a rendered pixmap via Tesseract."""
    img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    data = pytesseract.image_to_data(img, lang=lang, output_type=pytesseract.Output.DICT)
    words, parts = [], []
    for i, t in enumerate(data["text"]):
        t = (t or "").strip()
        if not t:
            continue
        parts.append(t)
        words.append({"t": t, "x0": data["left"][i], "y0": data["top"][i],
                      "x1": data["left"][i] + data["width"][i],
                      "y1": data["top"][i] + data["height"][i]})
    return " ".join(parts), words


def read_document(data: bytes, filename: str, settings: Settings) -> ReaderResult:
    doc = fitz.open(stream=data, filetype=_filetype(filename))
    pages: list[Page] = []
    used_ocr = False
    for page in doc:
        text = page.get_text().strip()
        if len(text) >= settings.text_threshold:
            words = [
                {"t": w[4], "x0": w[0] * _ZOOM, "y0": w[1] * _ZOOM,
                 "x1": w[2] * _ZOOM, "y1": w[3] * _ZOOM}
                for w in page.get_text("words")
            ]
            pages.append(Page(text=text, width=int(page.rect.width * _ZOOM),
                              height=int(page.rect.height * _ZOOM), words=words))
        else:
            used_ocr = True
            pix = page.get_pixmap(dpi=RENDER_DPI)
            otext, words = _ocr_page(pix, settings.ocr_lang)
            pages.append(Page(text=otext.strip(), width=pix.width,
                              height=pix.height, words=words))
    full = "\n".join(p.text for p in pages)
    return ReaderResult(pages=pages, full_text=full, used_ocr=used_ocr)


def render_page_png(data: bytes, filename: str, page_index: int) -> bytes:
    """Render a single page to PNG at RENDER_DPI (used by the review UI)."""
    doc = fitz.open(stream=data, filetype=_filetype(filename))
    pix = doc[page_index].get_pixmap(dpi=RENDER_DPI)
    return pix.tobytes("png")
