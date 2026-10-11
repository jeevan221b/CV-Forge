"""Groq implementation of AIProvider (OpenAI-compatible chat completions endpoint)."""
from __future__ import annotations

import json
import logging
import time
from typing import Any, Optional

import httpx

from ..config import Settings
from .provider import (
    AIAuthError, AIError, AIInvalidResponse, AINotConfigured, AIQuotaExceeded, AIRateLimited,
    AIRequestError, AITimeout, AIUnavailable,
)

log = logging.getLogger("cvforge.ai")

SETUP_HINT = ("AI tailoring is unavailable because GROQ_API_KEY is not set. Create a key at "
              "https://console.groq.com/keys, put it in backend/.env as GROQ_API_KEY=..., and restart the backend.")


class GroqProvider:
    name = "groq"

    def __init__(self, settings: Settings, transport: Optional[httpx.BaseTransport] = None,
                 sleep=time.sleep):
        self._settings = settings
        self._transport = transport
        self._sleep = sleep
        self.model = settings.groq_model

    def is_configured(self) -> bool:
        return self._settings.ai_configured

    # -- request construction -------------------------------------------------

    def build_payload(self, system: str, user: str, schema_name: str, json_schema: dict[str, Any]) -> dict[str, Any]:
        s = self._settings
        if s.use_strict_schema:
            response_format: dict[str, Any] = {
                "type": "json_schema",
                "json_schema": {"name": schema_name, "strict": True, "schema": json_schema},
            }
        else:
            # Documented fallback for models without constrained decoding: JSON object mode.
            # The schema travels in the prompt and the result is validated locally with Pydantic.
            response_format = {"type": "json_object"}
            system = (f"{system}\n\nRespond with a single JSON object and nothing else. It must conform to "
                      f"this JSON Schema:\n{json.dumps(json_schema, separators=(',', ':'))}")
        return {
            "model": s.groq_model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "temperature": s.groq_temperature,
            "max_completion_tokens": s.groq_max_completion_tokens,
            "response_format": response_format,
        }

    # -- transport ------------------------------------------------------------

    def complete_json(self, *, system: str, user: str, schema_name: str,
                      json_schema: dict[str, Any]) -> dict[str, Any]:
        s = self._settings
        if not s.ai_configured:
            raise AINotConfigured(SETUP_HINT)
        payload = self.build_payload(system, user, schema_name, json_schema)
        attempts = 1 + s.groq_max_retries
        last: Optional[AIError] = None
        for attempt in range(1, attempts + 1):
            started = time.monotonic()
            try:
                with httpx.Client(timeout=s.groq_timeout_seconds, transport=self._transport) as client:
                    response = client.post(
                        f"{s.groq_base_url}/chat/completions", json=payload,
                        headers={"Authorization": f"Bearer {s.groq_api_key}"},
                    )
            except httpx.TimeoutException:
                last = AITimeout(f"Groq did not answer within {s.groq_timeout_seconds:g} seconds.")
            except httpx.HTTPError:
                last = AIUnavailable("Could not reach Groq. Check your internet connection.")
            else:
                log.info("groq request model=%s status=%s attempt=%s seconds=%.1f", s.groq_model,
                         response.status_code, attempt, time.monotonic() - started)
                if response.status_code == 200:
                    return self._parse(response)
                last = self._error(response)
                if not isinstance(last, AIUnavailable):
                    raise last  # auth, rate limit, bad request: retrying will not help
            if attempt < attempts:
                self._sleep(min(2.0 * attempt, 5.0))
        assert last is not None
        raise last

    def _safe(self, text: str) -> str:
        key = self._settings.groq_api_key
        text = text.replace(key, "[redacted]") if key else text
        return text[:300]

    def _error(self, response: httpx.Response) -> AIError:
        status = response.status_code
        detail, code = "", ""
        try:
            err = response.json().get("error", {})
            if isinstance(err, dict):
                detail, code = str(err.get("message", "")), str(err.get("code", ""))
        except (ValueError, AttributeError):
            pass
        detail = self._safe(detail)
        suffix = f" Groq said: {detail}" if detail else ""
        if status in (401, 403):
            return AIAuthError("Groq rejected the API key. Check GROQ_API_KEY in backend/.env." if status == 401
                               else f"Groq denied access to this model or endpoint.{suffix}")
        if status == 429:
            retry_after: Optional[float] = None
            try:
                retry_after = float(response.headers.get("retry-after", ""))
            except ValueError:
                pass
            lowered = f"{detail} {code}".lower()
            if any(w in lowered for w in ("quota", "billing", "per day", "tpd", "rpd", "insufficient")):
                return AIQuotaExceeded(f"Your Groq quota is exhausted.{suffix}", retry_after=retry_after)
            wait = f" Try again in about {int(retry_after) + 1} seconds." if retry_after else " Try again shortly."
            return AIRateLimited(f"Groq rate limit reached.{wait} The request was not retried automatically.",
                                 retry_after=retry_after)
        if status == 404:
            return AIRequestError(f"Model '{self._settings.groq_model}' is not available for this account. "
                                  f"Set GROQ_MODEL to a model listed at https://console.groq.com/docs/models.{suffix}")
        if status == 413:
            return AIRequestError("The request was too large for the model. Shorten the job description or resume.")
        if status in (400, 422):
            if "json" in f"{detail} {code}".lower() or "schema" in detail.lower():
                return AIInvalidResponse(f"The model could not produce output matching the required schema.{suffix}")
            return AIRequestError(f"Groq rejected the request.{suffix}")
        if status >= 500 or status == 498:
            return AIUnavailable(f"Groq is temporarily unavailable (HTTP {status}). Try again later.")
        return AIRequestError(f"Unexpected response from Groq (HTTP {status}).{suffix}")

    def _parse(self, response: httpx.Response) -> dict[str, Any]:
        try:
            body = response.json()
            choice = body["choices"][0]
            content = choice["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise AIInvalidResponse("Groq returned a response in an unexpected format.") from exc
        usage = body.get("usage") or {}
        log.info("groq usage prompt_tokens=%s completion_tokens=%s", usage.get("prompt_tokens"),
                 usage.get("completion_tokens"))
        if choice.get("finish_reason") == "length":
            raise AIInvalidResponse("The model's answer was cut off before it finished. "
                                    "Raise GROQ_MAX_COMPLETION_TOKENS or tailor fewer items at once.")
        if not isinstance(content, str) or not content.strip():
            raise AIInvalidResponse("The model returned an empty answer.")
        try:
            data = json.loads(content)
        except ValueError as exc:
            raise AIInvalidResponse("The model's answer was not valid JSON.") from exc
        if not isinstance(data, dict):
            raise AIInvalidResponse("The model's answer was not a JSON object.")
        return data
