"""Gemini generateContent adapter using the existing httpx dependency."""

import os
import re
import time
import uuid
from typing import Any

import httpx

from agent.types import LLMResponse, ToolCall


class LLMRequestBudget:
    """Cap actual provider HTTP requests, including retries, for one run."""

    def __init__(self, max_requests: int = 12):
        if max_requests < 1:
            raise ValueError("LLM_MAX_REQUESTS_PER_RUN must be at least 1.")
        self.max_requests = max_requests
        self.used = 0

    def consume(self) -> None:
        if self.used >= self.max_requests:
            raise RuntimeError(
                f"Per-run LLM request limit reached ({self.max_requests}). "
                "No further provider request was sent."
            )
        self.used += 1


class GeminiClient:
    def __init__(
        self, api_key: str | None = None, model: str | None = None,
        request_budget: LLMRequestBudget | None = None,
    ):
        self.api_key = api_key or os.getenv("GEMINI_API_KEY", "")
        self.model = model or os.getenv("AGENT_MODEL", "gemini-3.8-flash")
        self.request_budget = request_budget or LLMRequestBudget(
            int(os.getenv("LLM_MAX_REQUESTS_PER_RUN", "12"))
        )
        if not self.api_key:
            raise ValueError("GEMINI_API_KEY is missing. Add it to .env.")

    def generate(
        self, system: str, messages: list[dict[str, Any]],
        tools: list[dict[str, Any]], max_tokens: int,
    ) -> LLMResponse:
        contents = []
        for message in messages:
            role = message.get("role", "user")
            parts = message.get("parts")
            if not parts:
                parts = [{"text": str(message.get("content", ""))}]
            contents.append({"role": role, "parts": parts})

        payload: dict[str, Any] = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": contents,
            "generationConfig": {"maxOutputTokens": max_tokens},
        }
        if tools:
            payload["tools"] = [{"functionDeclarations": tools}]
            payload["toolConfig"] = {"functionCallingConfig": {"mode": "AUTO"}}

        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self.model}:generateContent"
        )
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                self.request_budget.consume()
                response = httpx.post(
                    url, headers={"x-goog-api-key": self.api_key}, json=payload, timeout=60.0
                )
                if response.status_code == 429:
                    delay = self._retry_delay(response, fallback=2 ** attempt)
                    if attempt < 2 and delay <= 30:
                        time.sleep(delay)
                        continue
                    raise RuntimeError(
                        f"Gemini rate limit reached; server suggests retrying in "
                        f"{delay:.1f} seconds. {response.text[:1000]}"
                    )
                if response.status_code in {500, 502, 503, 504} and attempt < 2:
                    time.sleep(2 ** attempt)
                    continue
                response.raise_for_status()
                body = response.json()
                candidate = body["candidates"][0]
                text_parts = []
                calls = []
                for index, part in enumerate(candidate["content"].get("parts", [])):
                    if "text" in part:
                        text_parts.append(part["text"])
                    if "functionCall" in part:
                        item = part["functionCall"]
                        calls.append(ToolCall(
                            id=item.get("id", str(uuid.uuid4())),
                            name=item["name"], args=item.get("args", {}),
                        ))
                usage = body.get("usageMetadata", {})
                return LLMResponse(
                    text="\n".join(text_parts) or None,
                    tool_calls=calls,
                    input_tokens=usage.get("promptTokenCount", 0),
                    output_tokens=usage.get("candidatesTokenCount", 0),
                    raw_parts=candidate["content"].get("parts", []),
                )
            except (httpx.HTTPError, KeyError, IndexError, ValueError) as exc:
                last_error = exc
                if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code < 500:
                    raise RuntimeError(
                        f"Gemini API error {exc.response.status_code}: "
                        f"{exc.response.text[:1000]}"
                    ) from exc
                if attempt < 2:
                    time.sleep(2 ** attempt)
        raise RuntimeError(f"Gemini request failed after retries: {last_error}")

    @staticmethod
    def _retry_delay(response: httpx.Response, fallback: float) -> float:
        """Read a retry delay from standard headers or Google's error message."""
        header = response.headers.get("Retry-After", "").strip()
        try:
            return max(0.0, float(header))
        except ValueError:
            pass

        try:
            message = response.json().get("error", {}).get("message", "")
        except (ValueError, AttributeError):
            message = ""
        match = re.search(r"retry in ((?:\d+h)?(?:\d+m)?[\d.]+s)", message, re.IGNORECASE)
        if not match:
            return fallback

        delay_text = match.group(1).lower()
        hours = re.search(r"([\d.]+)h", delay_text)
        minutes = re.search(r"([\d.]+)m", delay_text)
        seconds = re.search(r"([\d.]+)s", delay_text)
        return (
            (float(hours.group(1)) * 3600 if hours else 0)
            + (float(minutes.group(1)) * 60 if minutes else 0)
            + (float(seconds.group(1)) if seconds else 0)
        )

