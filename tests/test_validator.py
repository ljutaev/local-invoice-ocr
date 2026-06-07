from invoiceflow import validator
from invoiceflow.schema import InvoiceFields, LineItem


def test_arithmetic_consistent_is_high():
    f = InvoiceFields(invoice_number="INV-1", invoice_date="2026-01-01",
                      subtotal=100.0, tax=20.0, total=120.0,
                      line_items=[LineItem(amount=100.0)])
    text = "INV-1 date 2026-01-01 subtotal 100.00 tax 20.00 total 120.00"
    flags, summary = validator.validate(f, text)
    assert flags["total"]["confidence"] == "high"
    assert summary == "high"


def test_total_mismatch_flags_low():
    f = InvoiceFields(invoice_number="INV-1", subtotal=100.0, tax=20.0, total=999.0,
                      line_items=[LineItem(amount=100.0)])
    text = "INV-1 subtotal 100.00 tax 20.00 total 999.00"
    flags, summary = validator.validate(f, text)
    assert flags["total"]["confidence"] == "low"
    assert "arithmetic" in flags["total"]["reasons"]


def test_value_not_in_text_is_low_grounding():
    f = InvoiceFields(invoice_number="INV-HALLUCINATED")
    text = "some invoice text without that number"
    flags, summary = validator.validate(f, text)
    assert flags["invoice_number"]["confidence"] == "low"
    assert "not_in_source" in flags["invoice_number"]["reasons"]


def test_missing_required_is_low():
    f = InvoiceFields()  # empty
    flags, summary = validator.validate(f, "")
    assert flags["invoice_number"]["confidence"] == "low"
    assert "missing" in flags["invoice_number"]["reasons"]
    assert summary == "low"
