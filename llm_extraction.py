"""Optional OpenRouter-backed extraction with privacy minimisation."""
from __future__ import annotations

import json
import os
import re
import socket
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from pydantic import BaseModel, ConfigDict, Field, ValidationError

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
_PHONE = re.compile(r"(?<!\d)(?:\+?91[-\s]?)?[6-9]\d{4}[-\s]?\d{5}(?!\d)")
_EMAIL = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)
_LABELLED_NAME = re.compile(
    r"\b(?P<label>customer(?:\s+name)?|name)\s*[:=-]\s*"
    r"(?P<name>[A-Za-z][A-Za-z .'-]{1,60}?)(?=[,;\n.]|$)",
    re.I,
)


class LLMExtractionError(RuntimeError):
    """Safe, user-facing failure from the optional extraction provider."""


class LLMUnavailableError(LLMExtractionError):
    pass


class LLMProviderError(LLMExtractionError):
    pass


class LLMResponseError(LLMExtractionError):
    pass


class _LLMLine(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_text: str = Field(min_length=1, max_length=300)
    quantity: int | None = Field(default=None, ge=1)
    unit: str | None = Field(default=None, max_length=40)
    source_text: str = Field(min_length=1, max_length=500)


class _LLMProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lines: list[_LLMLine] = Field(min_length=1, max_length=50)
    unrecognised_text: list[str] = Field(default_factory=list)
    delivery_instructions: str | None = Field(default=None, max_length=500)
    missing_fields: list[str] = Field(default_factory=list)
    ambiguous_fields: list[str] = Field(default_factory=list)


def mask_sensitive_text(message: str) -> str:
    """Mask confidently identified PII before an external provider sees a message.

    This is deliberately conservative: product and order details remain intact.
    It is risk reduction, not a guarantee that arbitrary free text is anonymous.
    """
    masked = _EMAIL.sub("<EMAIL>", message)
    masked = _PHONE.sub("<PHONE>", masked)
    return _LABELLED_NAME.sub(lambda match: f"{match.group('label')}: <CUSTOMER_NAME>", masked)


class OpenRouterExtractionAdapter:
    """Small, dependency-free OpenRouter chat-completions adapter."""

    def __init__(self, *, api_key: str | None, model: str | None, timeout_seconds: float = 15) -> None:
        self.api_key = api_key or ""
        self.model = model or ""
        self.timeout_seconds = timeout_seconds

    @classmethod
    def from_environment(cls) -> "OpenRouterExtractionAdapter":
        timeout = os.getenv("OPENROUTER_TIMEOUT_SECONDS", "15")
        try:
            timeout_seconds = max(1, float(timeout))
        except ValueError:
            timeout_seconds = 15
        return cls(
            api_key=os.getenv("OPENROUTER_API_KEY"),
            model=os.getenv("OPENROUTER_MODEL"),
            timeout_seconds=timeout_seconds,
        )

    @property
    def is_available(self) -> bool:
        return bool(self.api_key and self.model)

    def extract(self, message: str) -> dict[str, Any]:
        if not self.is_available:
            raise LLMUnavailableError("LLM extraction is unavailable: configure OPENROUTER_API_KEY and OPENROUTER_MODEL.")

        masked_message = mask_sensitive_text(message)
        payload = {
            "model": self.model,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Extract order proposals only. Return JSON with lines, unrecognised_text, "
                        "delivery_instructions, missing_fields, and ambiguous_fields. Each line must contain "
                        "product_text, quantity (or null), unit (or null), and source_text. Never return prices, "
                        "SKUs, inventory, approvals, or pack conversion assumptions."
                    ),
                },
                {"role": "user", "content": masked_message},
            ],
        }
        request = Request(
            OPENROUTER_URL,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                response_data = json.loads(response.read().decode("utf-8"))
        except socket.timeout as exc:
            raise LLMProviderError("LLM provider request timed out.") from exc
        except (HTTPError, URLError, OSError) as exc:
            raise LLMProviderError("LLM provider request failed.") from exc
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise LLMResponseError("LLM provider returned an invalid response.") from exc

        try:
            content = response_data["choices"][0]["message"]["content"]
            proposal = _LLMProposal.model_validate_json(content)
        except (KeyError, IndexError, TypeError, ValidationError, json.JSONDecodeError) as exc:
            raise LLMResponseError("LLM provider returned an invalid extraction proposal.") from exc

        return {
            "method": "llm",
            "version": "openrouter-chat-completions-v1",
            "lines": [line.model_dump() for line in proposal.lines],
            "unrecognised_text": proposal.unrecognised_text,
            "delivery_instructions": proposal.delivery_instructions,
            "missing_fields": proposal.missing_fields,
            "ambiguous_fields": proposal.ambiguous_fields,
        }
