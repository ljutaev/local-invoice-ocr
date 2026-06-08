from pathlib import Path

from fastapi import FastAPI, File, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from invoiceflow import ingest, reader, store
from invoiceflow.config import Settings, ensure_dirs
from invoiceflow.db import init_db
from invoiceflow.schema import InvoiceFields

_DIR = Path(__file__).parent
_USER = "reviewer"  # single-user local app for now

# scalar fields editable in the MVP form (line items shown read-only)
_EDIT_FIELDS = ["invoice_number", "invoice_date", "due_date", "buyer_name",
                "currency", "subtotal", "tax", "total", "po_number", "payment_terms"]
_NUMERIC = {"subtotal", "tax", "total"}


def _to_float(v):
    v = (v or "").strip()
    return float(v) if v else None


def create_app(settings: Settings) -> FastAPI:
    ensure_dirs(settings)
    init_db(settings)
    app = FastAPI(title="local-invoice-ocr")
    templates = Jinja2Templates(directory=str(_DIR / "templates"))
    app.mount("/static", StaticFiles(directory=str(_DIR / "static")), name="static")

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request, status: str | None = None):
        rows = store.list_invoice_summaries(status=status)
        return templates.TemplateResponse(
            request=request, name="list.html",
            context={"rows": rows, "status": status})

    @app.get("/invoice/{invoice_id}", response_class=HTMLResponse)
    def detail(request: Request, invoice_id: int):
        inv = store.get_invoice(invoice_id)
        return templates.TemplateResponse(request=request, name="detail.html", context={
            "inv": inv, "fields": inv.fields, "flags": inv.flags,
            "edit_fields": _EDIT_FIELDS, "layout": inv.layout or {"pages": []},
        })

    @app.get("/invoice/{invoice_id}/file")
    def original(invoice_id: int):
        data, media = store.get_original_bytes(invoice_id)
        return Response(content=data, media_type=media)

    @app.get("/invoice/{invoice_id}/page/{page_index}.png")
    def page_png(invoice_id: int, page_index: int):
        data, media = store.get_original_bytes(invoice_id)
        name = "x.pdf" if media == "application/pdf" else "x.png"
        png = reader.render_page_png(data, name, page_index)
        return Response(content=png, media_type="image/png")

    @app.post("/invoice/{invoice_id}")
    async def save(invoice_id: int, request: Request):
        form = await request.form()
        cur = store.get_invoice(invoice_id).fields
        data = cur.model_dump()
        for k in _EDIT_FIELDS:
            v = form.get(k)
            if v is None:
                continue
            v = v.strip()
            if k in _NUMERIC:
                data[k] = float(v) if v else None
            else:
                data[k] = v
        data["vendor"] = {
            "name": (form.get("vendor_name") or "").strip(),
            "address": (form.get("vendor_address") or "").strip(),
            "tax_id": (form.get("vendor_tax_id") or "").strip(),
        }
        li_keys = [k for k in form.keys() if k.startswith("li_")]
        if li_keys:
            items: dict[int, dict] = {}
            for k in li_keys:
                _, idx, fld = k.split("_", 2)
                items.setdefault(int(idx), {})[fld] = (form.get(k) or "").strip()
            data["line_items"] = [
                {
                    "description": items[i].get("description", ""),
                    "qty": _to_float(items[i].get("qty")),
                    "unit_price": _to_float(items[i].get("unit_price")),
                    "amount": _to_float(items[i].get("amount")),
                }
                for i in sorted(items)
            ]
        store.update_invoice_fields(invoice_id, InvoiceFields(**data), _USER)
        return RedirectResponse(f"/invoice/{invoice_id}", status_code=303)

    @app.post("/invoice/{invoice_id}/approve")
    def approve(invoice_id: int):
        store.approve_invoice(invoice_id, _USER)
        return RedirectResponse("/", status_code=303)

    @app.post("/upload")
    async def upload(file: UploadFile = File(...)):
        ingest.UploadSource(settings).ingest_bytes(await file.read(), file.filename)
        return RedirectResponse("/", status_code=303)

    return app
