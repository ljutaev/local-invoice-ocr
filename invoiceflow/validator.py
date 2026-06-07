import re

from invoiceflow.schema import InvoiceFields

_REQUIRED = ["invoice_number", "invoice_date", "total"]
_TOL = 0.01


def _norm(s: str) -> str:
    return re.sub(r"\s+", "", s).lower()


def _grounded(value, source_norm: str) -> bool:
    if value is None or value == "":
        return False
    return _norm(str(value)) in source_norm


def validate(fields: InvoiceFields, source_text: str) -> tuple[dict, str]:
    src = _norm(source_text)
    flags: dict = {}

    def mark(field, value, *, required=False):
        reasons = []
        if value in (None, ""):
            if required:
                reasons.append("missing")
        elif not _grounded(value, src):
            reasons.append("not_in_source")
        flags[field] = {"confidence": "low" if reasons else "high", "reasons": reasons}

    mark("invoice_number", fields.invoice_number, required=True)
    mark("invoice_date", fields.invoice_date, required=True)
    mark("total", fields.total, required=True)
    mark("subtotal", fields.subtotal)
    mark("tax", fields.tax)
    mark("vendor_name", fields.vendor.name)

    # arithmetic cross-checks override grounding for the involved fields
    if fields.subtotal is not None and fields.tax is not None and fields.total is not None:
        if abs((fields.subtotal + fields.tax) - fields.total) > _TOL:
            flags["total"] = {"confidence": "low", "reasons": ["arithmetic"]}
    line_sum = sum(li.amount for li in fields.line_items if li.amount is not None)
    if fields.line_items and fields.subtotal is not None:
        if abs(line_sum - fields.subtotal) > _TOL:
            flags["subtotal"] = {"confidence": "low",
                                 "reasons": flags.get("subtotal", {}).get("reasons", []) + ["arithmetic"]}

    summary = "low" if any(v["confidence"] == "low" for v in flags.values()) else "high"
    return flags, summary
