import json

import httpx

from invoiceflow.config import Settings
from invoiceflow.schema import INVOICE_JSON_SCHEMA, InvoiceFields

_SYS = (
    "You extract structured data from invoice text. "
    "Return ONLY fields supported by the text. Use empty string / null when unknown. "
    "Never invent values that are not present."
)


class ExtractionError(Exception):
    pass


def extract_fields(text: str, settings: Settings) -> InvoiceFields:
    body = {
        "model": settings.model,
        "stream": False,
        "format": INVOICE_JSON_SCHEMA,
        "messages": [
            {"role": "system", "content": _SYS},
            {"role": "user", "content": f"Invoice text:\n\n{text}"},
        ],
    }
    try:
        resp = httpx.post(f"{settings.ollama_url}/api/chat", json=body, timeout=120)
        resp.raise_for_status()
        content = resp.json()["message"]["content"]
        return InvoiceFields.model_validate_json(content)
    except (httpx.HTTPError, KeyError) as e:
        raise ExtractionError(f"ollama call failed: {e}") from e
    except (json.JSONDecodeError, ValueError) as e:
        raise ExtractionError(f"invalid model JSON: {e}") from e
