import fitz  # PyMuPDF


def to_pdf(data: bytes, filename: str) -> bytes:
    """Return a PDF rendition of the input.

    PDFs pass through unchanged. Images (png/jpg/...) are wrapped into a PDF —
    CargoWise (and many systems) accept only PDF, so this removes the manual
    "convert to PDF" step.
    """
    if filename.lower().endswith(".pdf"):
        return data
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else None
    doc = fitz.open(stream=data, filetype=ext)
    return doc.convert_to_pdf()
