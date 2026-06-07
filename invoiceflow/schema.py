from pydantic import BaseModel, Field


class LineItem(BaseModel):
    description: str = ""
    qty: float | None = None
    unit_price: float | None = None
    amount: float | None = None


class Vendor(BaseModel):
    name: str = ""
    address: str = ""
    tax_id: str = ""


class InvoiceFields(BaseModel):
    invoice_number: str = ""
    invoice_date: str = ""
    due_date: str = ""
    vendor: Vendor = Field(default_factory=Vendor)
    buyer_name: str = ""
    currency: str = ""
    line_items: list[LineItem] = Field(default_factory=list)
    subtotal: float | None = None
    tax: float | None = None
    total: float | None = None
    po_number: str = ""
    payment_terms: str = ""


# JSON schema handed to Ollama `format` to force valid structured output.
INVOICE_JSON_SCHEMA = InvoiceFields.model_json_schema()
