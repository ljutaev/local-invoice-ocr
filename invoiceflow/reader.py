from dataclasses import dataclass, field

import fitz  # PyMuPDF
import pytesseract
from PIL import Image

from invoiceflow.config import Settings


@dataclass
class Page:
    text: str
    boxes: list = field(default_factory=list)  # [(word, x0,y0,x1,y1)] when OCR


@dataclass
class ReaderResult:
    pages: list[Page]
    full_text: str
    used_ocr: bool


def _ocr_page(pix: "fitz.Pixmap", lang: str) -> str:
    img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    return pytesseract.image_to_string(img, lang=lang)


def read_document(data: bytes, filename: str, settings: Settings) -> ReaderResult:
    doc = fitz.open(stream=data, filetype="pdf" if filename.lower().endswith(".pdf") else None)
    pages: list[Page] = []
    used_ocr = False
    for page in doc:
        text = page.get_text().strip()
        if len(text) >= settings.text_threshold:
            pages.append(Page(text=text))
        else:
            used_ocr = True
            pix = page.get_pixmap(dpi=200)
            pages.append(Page(text=_ocr_page(pix, settings.ocr_lang).strip()))
    full = "\n".join(p.text for p in pages)
    return ReaderResult(pages=pages, full_text=full, used_ocr=used_ocr)
