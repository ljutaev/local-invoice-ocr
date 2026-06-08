import fitz  # PyMuPDF

from invoiceflow import reader
from invoiceflow.config import get_settings


def _make_text_pdf() -> bytes:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text(
        (72, 72),
        "INVOICE INV-42\n"
        "Vendor: Acme Corporation Ltd\n"
        "Date: 2026-01-01   Due: 2026-02-01\n"
        "Description       Qty   Unit    Amount\n"
        "Widgets            10   9.90    99.00\n"
        "Subtotal 99.00   Tax 0.00   TOTAL 99.00\n"
        "Thank you for your business.",
    )
    return doc.tobytes()


def test_digital_pdf_uses_text_not_ocr(tmp_path):
    s = get_settings(str(tmp_path))
    result = reader.read_document(_make_text_pdf(), "a.pdf", s)
    assert "INV-42" in result.full_text
    assert result.used_ocr is False


def test_imageonly_pdf_routes_to_ocr(tmp_path, monkeypatch):
    s = get_settings(str(tmp_path))
    # blank PDF (no text layer) → OCR path; stub OCR to avoid tesseract dep in unit test.
    # _ocr_page now returns (text, word-boxes).
    monkeypatch.setattr(reader, "_ocr_page",
                        lambda pix, lang: ("OCR TEXT INV-7", [{"t": "INV-7", "x0": 1, "y0": 2, "x1": 3, "y1": 4}]))
    blank = fitz.open()
    blank.new_page()
    result = reader.read_document(blank.tobytes(), "scan.pdf", s)
    assert result.used_ocr is True
    assert "INV-7" in result.full_text
    assert result.pages[0].words[0]["t"] == "INV-7"


def test_digital_pdf_has_word_boxes(tmp_path):
    s = get_settings(str(tmp_path))
    r = reader.read_document(_make_text_pdf(), "a.pdf", s)
    pg = r.pages[0]
    assert pg.width > 0 and pg.height > 0
    assert any("INV-42" in w["t"] for w in pg.words)


def test_render_page_png_returns_png(tmp_path):
    data = reader.render_page_png(_make_text_pdf(), "a.pdf", 0)
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
