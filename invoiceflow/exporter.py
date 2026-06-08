import csv
import json
from pathlib import Path

from invoiceflow import store
from invoiceflow.schema import InvoiceFields

_COLUMNS = ["id", "invoice_number", "invoice_date", "due_date", "vendor_name",
            "vendor_address", "vendor_tax_id", "buyer_name", "currency",
            "subtotal", "tax", "total", "po_number", "payment_terms", "line_items"]


def _flatten(invoice_id: int, f: InvoiceFields) -> dict:
    return {
        "id": invoice_id,
        "invoice_number": f.invoice_number,
        "invoice_date": f.invoice_date,
        "due_date": f.due_date,
        "vendor_name": f.vendor.name,
        "vendor_address": f.vendor.address,
        "vendor_tax_id": f.vendor.tax_id,
        "buyer_name": f.buyer_name,
        "currency": f.currency,
        "subtotal": f.subtotal,
        "tax": f.tax,
        "total": f.total,
        "po_number": f.po_number,
        "payment_terms": f.payment_terms,
        "line_items": json.dumps([li.model_dump() for li in f.line_items]),
    }


def export_verified(out_path, fmt: str = "csv") -> int:
    """Export verified, not-yet-exported invoices to CSV/JSON. Returns count."""
    rows = store.list_verified_unexported()
    if not rows:
        return 0
    records = [_flatten(r["id"], r["fields"]) for r in rows]
    out_path = Path(out_path)
    if fmt == "json":
        out_path.write_text(json.dumps(records, indent=2, default=str))
    else:
        with out_path.open("w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=_COLUMNS)
            w.writeheader()
            w.writerows(records)
    store.mark_exported([r["id"] for r in records])
    return len(records)
