import io

import fitz
from PIL import Image

from invoiceflow import convert


def _png_bytes() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (60, 40), (255, 255, 255)).save(buf, "PNG")
    return buf.getvalue()


def test_pdf_passthrough():
    doc = fitz.open()
    doc.new_page()
    pdf = doc.tobytes()
    assert convert.to_pdf(pdf, "a.pdf") == pdf


def test_png_converted_to_pdf():
    out = convert.to_pdf(_png_bytes(), "scan.png")
    assert out[:5] == b"%PDF-"
    # the result is a real, openable single-page PDF
    doc = fitz.open(stream=out, filetype="pdf")
    assert doc.page_count == 1
