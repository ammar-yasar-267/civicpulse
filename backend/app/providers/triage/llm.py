"""Hosted-LLM triage (Groq by default; any OpenAI-compatible base_url works).

Uses httpx directly against the chat-completions endpoint rather than the openai SDK:
one fewer dependency, and the timeout and error-class mapping the orchestrator needs are
explicit here instead of buried in someone else's retry logic.

The API key is read from settings, which reads the environment. It is never logged, never
included in an exception message and never written to disk (§2.5 rule 6).
"""

import httpx

from app.config import Settings
from app.providers.triage.base import (
    TriageBadRequest,
    TriageRateLimited,
    TriageTimeout,
    TriageUpstreamError,
)
from app.providers.triage.prompt import (
    RESPONSE_JSON_SCHEMA,
    SYSTEM_PROMPT,
    build_user_prompt,
    parse_triage_response,
)
from app.schemas import TriageResult


class LLMTriage:
    """Production path. Calls a free-tier hosted model."""

    name = "llm:groq"

    def __init__(self, settings: Settings) -> None:
        if not settings.groq_api_key:
            raise ValueError(
                "TRIAGE_PROVIDER=llm requires GROQ_API_KEY in the environment. "
                "Use TRIAGE_PROVIDER=ollama for the offline path or 'rules' for keywords."
            )
        self._settings = settings
        self._url = f"{settings.groq_base_url.rstrip('/')}/chat/completions"
        self._model = settings.groq_model
        self._timeout = settings.triage_timeout_seconds
        self._key = settings.groq_api_key

    def _body(self, text: str, location: str) -> dict:
        return {
            "model": self._model,
            # Classification, not composition: no creativity wanted, and a low
            # temperature makes the content-hash cache worth more.
            "temperature": 0.1,
            "max_tokens": 300,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "triage_result",
                    "strict": True,
                    "schema": RESPONSE_JSON_SCHEMA,
                },
            },
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": build_user_prompt(text, location)},
            ],
        }

    def triage(self, text: str, location: str) -> TriageResult:
        try:
            response = httpx.post(
                self._url,
                json=self._body(text, location),
                headers={
                    "Authorization": f"Bearer {self._key}",
                    "Content-Type": "application/json",
                },
                timeout=self._timeout,
            )
        except httpx.TimeoutException as exc:
            # Deliberately does not interpolate the request: the Authorization header
            # must not reach a log line via an exception string.
            raise TriageTimeout(f"{self.name} timed out after {self._timeout}s") from exc
        except httpx.HTTPError as exc:
            raise TriageUpstreamError(f"{self.name} transport error: {type(exc).__name__}") from exc

        self._raise_for_status(response)

        payload = response.json()
        try:
            content = payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise TriageUpstreamError(f"{self.name} returned an unexpected envelope") from exc

        # Raises TriageMalformedOutput if the model ignored the schema. The caller turns
        # that into a rules fallback.
        return parse_triage_response(content or "")

    def _raise_for_status(self, response: httpx.Response) -> None:
        status = response.status_code
        if status < 400:
            return
        if status == 429:
            raise TriageRateLimited(f"{self.name} rate limited (429)")
        if status >= 500:
            raise TriageUpstreamError(f"{self.name} upstream error ({status})")
        # 400/401/403/404: the request or the credential is wrong. Retrying an identical
        # request cannot fix it (§2.5 rule 3), so this class is not retryable.
        raise TriageBadRequest(f"{self.name} rejected the request ({status})")


class OllamaTriage:
    """Fully offline path — a container in the Compose stack. Same interface, no key, no
    network egress, no PII leaving the machine (see docs/adr/0004-pii-and-data-governance.md)."""

    name = "llm:ollama"

    def __init__(self, settings: Settings) -> None:
        self._url = f"{settings.ollama_base_url.rstrip('/')}/api/chat"
        self._model = settings.ollama_model
        self._timeout = settings.triage_timeout_seconds

    def triage(self, text: str, location: str) -> TriageResult:
        body = {
            "model": self._model,
            "stream": False,
            # Ollama's structured-output support: a JSON schema it constrains decoding to.
            "format": RESPONSE_JSON_SCHEMA,
            "options": {"temperature": 0.1},
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": build_user_prompt(text, location)},
            ],
        }
        try:
            response = httpx.post(self._url, json=body, timeout=self._timeout)
        except httpx.TimeoutException as exc:
            # A 1B model on laptop CPU genuinely is slow; the 10s cap will bite here more
            # often than against Groq, and the fallback is what keeps the UX honest.
            raise TriageTimeout(f"{self.name} timed out after {self._timeout}s") from exc
        except httpx.HTTPError as exc:
            raise TriageUpstreamError(f"{self.name} transport error: {type(exc).__name__}") from exc

        if response.status_code >= 500:
            raise TriageUpstreamError(f"{self.name} upstream error ({response.status_code})")
        if response.status_code >= 400:
            raise TriageBadRequest(f"{self.name} rejected the request ({response.status_code})")

        payload = response.json()
        content = (payload.get("message") or {}).get("content", "")
        return parse_triage_response(content or "")
