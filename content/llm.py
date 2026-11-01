"""Abstracted LLM client used by the build-time content pipeline.

The project talks to exactly one language model, from one place, for a
handful of build-time calls. This module keeps that single point of contact
small, explicit and reproducible:

* :class:`LLMProvider` is the protocol every provider implements.
* :class:`OpenAIProvider` and :class:`AnthropicProvider` are the two
  concrete backends, built on :mod:`urllib.request` from the standard
  library so that the project gains no new dependency.
* :func:`provider_from_env` picks a backend from the environment variables.
* :class:`DiskCache` stores every answer on disk, keyed by a hash of the
  request, so regenerating unchanged content costs nothing.

Reproducibility
---------------
Two runs of the pipeline with the same prompt, the same model, the same
temperature and the same seed must produce the same bytes. That is achieved
in three places:

1. The **seed** is part of the request (OpenAI receives it as the native
   ``seed`` parameter; Anthropic has no such parameter, so the seed is
   injected into the prompt as an explicit instruction -- see
   :meth:`AnthropicProvider._inject_seed`).
2. The **cache key** includes the seed, so the same prompt with a different
   seed is a different entry and never reuses the previous answer.
3. The **cache** itself is deterministic: the same request always maps to
   the same file, and a cache hit skips the API call entirely.

Secrets
-------
The API key is read from the environment and is never written to disk, never
logged and never included in an error message. :class:`LLMRequestError`
carries the HTTP status code and a sanitised excerpt of the response body,
with anything that looks like a key removed.

Usage:
    from content.llm import provider_from_env

    provider = provider_from_env()
    answer = provider.complete("Write a rumor about the harbour.", seed=20260514)
"""

from __future__ import annotations

import hashlib
import json
import os
import urllib.error
import urllib.request
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

__all__ = [
    "AnthropicProvider",
    "DiskCache",
    "LLMError",
    "LLMNotConfiguredError",
    "LLMProvider",
    "LLMRequestError",
    "LLMResponse",
    "OpenAIProvider",
    "cache_key",
    "provider_from_env",
]

#: Default model used when ``ALDERMERE_LLM_MODEL`` is not set.
DEFAULT_OPENAI_MODEL = "gpt-4o-mini"

#: Default model used when ``ALDERMERE_LLM_MODEL`` is not set.
DEFAULT_ANTHROPIC_MODEL = "claude-sonnet-4-5"

#: Default sampling temperature of the content pipeline.
DEFAULT_TEMPERATURE = 0.7

#: Environment variable that selects the model for whichever provider is used.
MODEL_ENV_VAR = "ALDERMERE_LLM_MODEL"

#: Environment variable holding the OpenAI API key.
OPENAI_KEY_ENV_VAR = "OPENAI_API_KEY"

#: Environment variable holding the Anthropic API key.
ANTHROPIC_KEY_ENV_VAR = "ANTHROPIC_API_KEY"

#: Root of the on-disk cache of LLM answers.
CACHE_DIR = Path(__file__).resolve().parent.parent / ".cache" / "llm"

#: OpenAI chat completions endpoint.
OPENAI_ENDPOINT = "https://api.openai.com/v1/chat/completions"

#: Anthropic messages endpoint.
ANTHROPIC_ENDPOINT = "https://api.anthropic.com/v1/messages"

#: Anthropic API version header.
ANTHROPIC_VERSION = "2023-06-01"

#: Maximum number of characters of a response body kept in an error message.
_ERROR_BODY_LIMIT = 240


class LLMError(Exception):
    """Base class of every failure raised by the LLM layer."""


class LLMNotConfiguredError(LLMError):
    """Raised when no provider can be built from the environment.

    The message names the environment variables the user has to export, so
    the failure is actionable without reading the source.
    """


class LLMRequestError(LLMError):
    """Raised when a provider call fails.

    Attributes:
        status_code: HTTP status code of the failed call, when the failure
            came from an HTTP response.
        provider: Name of the provider that failed.
    """

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        provider: str = "",
    ) -> None:
        """Build the error.

        Args:
            message: Sanitised description of the failure.
            status_code: HTTP status code, when known.
            provider: Name of the provider that failed.
        """
        super().__init__(message)
        self.status_code = status_code
        self.provider = provider


@runtime_checkable
class LLMProvider(Protocol):
    """Protocol every LLM backend implements.

    A provider is a thin, stateless adapter: it takes a prompt and returns
    the raw text of the answer. Reproducibility, caching and validation live
    in the pipeline, not in the provider.
    """

    name: str
    model: str

    def complete(self, prompt: str, system: str | None = None) -> str:
        """Send a prompt to the model and return the answer.

        Args:
            prompt: The user prompt.
            system: Optional system prompt.

        Returns:
            The text produced by the model.

        Raises:
            LLMRequestError: If the call fails.
        """
        ...


@dataclass(frozen=True)
class LLMResponse:
    """A completed call, with the metadata the manifest records.

    Attributes:
        text: Text produced by the model.
        model: Model that produced the text.
        provider: Name of the provider that was used.
        seed: Seed that was sent with the request.
        temperature: Sampling temperature of the request.
        cached: Whether the text came from the on-disk cache.
    """

    text: str
    model: str
    provider: str
    seed: int
    temperature: float
    cached: bool = False


def _sanitize(text: str, secrets: tuple[str, ...] = ()) -> str:
    """Remove anything that looks like a secret from a string.

    Args:
        text: Text to sanitise.
        secrets: Known secret values to redact.

    Returns:
        The text with the secrets replaced by a placeholder.
    """
    result = text
    for secret in secrets:
        if secret:
            result = result.replace(secret, "<redacted>")
    return result


def _sanitize_body(body: str, secrets: tuple[str, ...] = ()) -> str:
    """Build a short, safe excerpt of a response body.

    Args:
        body: Raw response body.
        secrets: Known secret values to redact.

    Returns:
        An excerpt of the body, with the secrets removed.
    """
    cleaned = _sanitize(body, secrets).replace("\n", " ").strip()
    if len(cleaned) > _ERROR_BODY_LIMIT:
        cleaned = cleaned[:_ERROR_BODY_LIMIT] + "..."
    return cleaned


def cache_key(
    prompt: str,
    system: str | None,
    model: str,
    temperature: float,
    seed: int,
) -> str:
    """Compute the cache key of a request.

    The key covers everything that can change the answer: the prompt, the
    system prompt, the model, the temperature and the **seed**. Two requests
    that differ in any of them must never share a cache entry.

    Args:
        prompt: The user prompt.
        system: The system prompt, if any.
        model: Model identifier.
        temperature: Sampling temperature.
        seed: Random seed sent with the request.

    Returns:
        The hexadecimal sha256 digest of the request.
    """
    payload = json.dumps(
        {
            "prompt": prompt,
            "system": system or "",
            "model": model,
            "temperature": temperature,
            "seed": seed,
        },
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class DiskCache:
    """A content-addressed cache of LLM answers stored on disk.

    Each entry lives in ``<root>/<sha256>.json`` and holds the answer plus
    the metadata needed to explain where it came from.

    Attributes:
        root: Directory holding the cache entries.
    """

    def __init__(self, root: str | Path = CACHE_DIR) -> None:
        """Build the cache.

        Args:
            root: Directory holding the cache entries.
        """
        self.root = Path(root)

    def path_for(self, key: str) -> Path:
        """Return the file that holds a cache entry.

        Args:
            key: Cache key of the entry.

        Returns:
            Path of the cache file.
        """
        return self.root / f"{key}.json"

    def get(self, key: str) -> LLMResponse | None:
        """Read a cache entry.

        Args:
            key: Cache key of the entry.

        Returns:
            The cached response, or ``None`` when the entry is missing or
            unreadable.
        """
        path = self.path_for(key)
        if not path.is_file():
            return None
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except OSError, json.JSONDecodeError:
            return None
        text = document.get("text")
        if not isinstance(text, str):
            return None
        return LLMResponse(
            text=text,
            model=str(document.get("model", "")),
            provider=str(document.get("provider", "")),
            seed=int(document.get("seed", 0)),
            temperature=float(document.get("temperature", DEFAULT_TEMPERATURE)),
            cached=True,
        )

    def put(self, key: str, response: LLMResponse) -> Path:
        """Write a cache entry.

        Args:
            key: Cache key of the entry.
            response: Response to store.

        Returns:
            Path of the written file.
        """
        self.root.mkdir(parents=True, exist_ok=True)
        path = self.path_for(key)
        document = {
            "text": response.text,
            "model": response.model,
            "provider": response.provider,
            "seed": response.seed,
            "temperature": response.temperature,
        }
        path.write_text(
            json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return path


class _BaseProvider:
    """Shared plumbing of the concrete providers.

    Attributes:
        name: Name of the provider.
        model: Model identifier used for the requests.
        temperature: Sampling temperature of the requests.
        seed: Seed sent with every request.
        cache: Cache consulted before every request.
    """

    name = "base"
    model = ""

    def __init__(
        self,
        api_key: str,
        *,
        model: str | None = None,
        temperature: float = DEFAULT_TEMPERATURE,
        seed: int = 0,
        cache: DiskCache | None = None,
        timeout: float = 120.0,
    ) -> None:
        """Build the provider.

        Args:
            api_key: API key of the provider.
            model: Model identifier. Defaults to the provider default.
            temperature: Sampling temperature.
            seed: Seed sent with every request.
            cache: Cache consulted before every request.
            timeout: Timeout of the HTTP call, in seconds.

        Raises:
            LLMNotConfiguredError: If the API key is empty.
        """
        if not api_key:
            raise LLMNotConfiguredError(f"the {self.name} provider needs an API key")
        self._api_key = api_key
        self.model = model or self._default_model()
        self.temperature = temperature
        self.seed = seed
        self.cache = cache if cache is not None else DiskCache()
        self.timeout = timeout

    def _default_model(self) -> str:
        """Return the default model of the provider.

        Returns:
            The default model identifier.
        """
        return DEFAULT_OPENAI_MODEL

    def _build_request(self, prompt: str, system: str | None) -> urllib.request.Request:
        """Build the HTTP request of a call.

        Args:
            prompt: The user prompt.
            system: The system prompt, if any.

        Returns:
            The prepared request.

        Raises:
            NotImplementedError: Always, in the base class.
        """
        raise NotImplementedError

    def _extract_text(self, payload: Mapping[str, Any]) -> str:
        """Extract the answer text out of a response payload.

        Args:
            payload: Decoded response body.

        Returns:
            The answer text.

        Raises:
            NotImplementedError: Always, in the base class.
        """
        raise NotImplementedError

    def _post(self, request: urllib.request.Request) -> str:
        """Send a request and decode the response.

        Args:
            request: The prepared request.

        Returns:
            The raw response body.

        Raises:
            LLMRequestError: If the call fails.
        """
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                body = response.read().decode("utf-8")
        except urllib.error.HTTPError as error:
            raw = error.read().decode("utf-8", errors="replace")
            excerpt = _sanitize_body(raw, (self._api_key,))
            raise LLMRequestError(
                f"{self.name} request failed with HTTP {error.code}: {excerpt}",
                status_code=error.code,
                provider=self.name,
            ) from error
        except urllib.error.URLError as error:
            raise LLMRequestError(
                f"{self.name} request failed: {error.reason}",
                provider=self.name,
            ) from error
        except TimeoutError as error:
            raise LLMRequestError(
                f"{self.name} request timed out after {self.timeout} seconds",
                provider=self.name,
            ) from error
        return body

    def complete(self, prompt: str, system: str | None = None) -> str:
        """Send a prompt to the model and return the answer.

        The cache is consulted first: a hit skips the network call entirely.

        Args:
            prompt: The user prompt.
            system: Optional system prompt.

        Returns:
            The text produced by the model.

        Raises:
            LLMRequestError: If the call fails or the answer cannot be
                decoded.
        """
        key = cache_key(prompt, system, self.model, self.temperature, self.seed)
        cached = self.cache.get(key)
        if cached is not None:
            return cached.text

        request = self._build_request(prompt, system)
        body = self._post(request)
        try:
            payload = json.loads(body)
        except json.JSONDecodeError as error:
            raise LLMRequestError(
                f"{self.name} returned a body that is not valid JSON",
                provider=self.name,
            ) from error
        if not isinstance(payload, dict):
            raise LLMRequestError(
                f"{self.name} returned a body that is not a JSON object",
                provider=self.name,
            )
        text = self._extract_text(payload)
        self.cache.put(
            key,
            LLMResponse(
                text=text,
                model=self.model,
                provider=self.name,
                seed=self.seed,
                temperature=self.temperature,
            ),
        )
        return text


class OpenAIProvider(_BaseProvider):
    """Provider backed by the OpenAI chat completions API.

    The seed is sent as the native ``seed`` parameter of the request, which
    the API uses to make the sampling reproducible for the same prompt and
    the same seed.
    """

    name = "openai"

    def _default_model(self) -> str:
        """Return the default model of the provider.

        Returns:
            The default model identifier.
        """
        return DEFAULT_OPENAI_MODEL

    def _build_request(self, prompt: str, system: str | None) -> urllib.request.Request:
        """Build the HTTP request of a call.

        Args:
            prompt: The user prompt.
            system: The system prompt, if any.

        Returns:
            The prepared request.
        """
        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        body = json.dumps(
            {
                "model": self.model,
                "messages": messages,
                "temperature": self.temperature,
                "seed": self.seed,
            },
            ensure_ascii=False,
        ).encode("utf-8")
        request = urllib.request.Request(
            OPENAI_ENDPOINT,
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self._api_key}",
            },
        )
        return request

    def _extract_text(self, payload: Mapping[str, Any]) -> str:
        """Extract the answer text out of a response payload.

        Args:
            payload: Decoded response body.

        Returns:
            The answer text.

        Raises:
            LLMRequestError: If the payload has no usable answer.
        """
        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices:
            raise LLMRequestError(
                "the openai response holds no choices",
                provider=self.name,
            )
        first = choices[0]
        if not isinstance(first, dict):
            raise LLMRequestError(
                "the openai response holds a malformed choice",
                provider=self.name,
            )
        message = first.get("message")
        if not isinstance(message, dict):
            raise LLMRequestError(
                "the openai response holds no message",
                provider=self.name,
            )
        content = message.get("content")
        if not isinstance(content, str):
            raise LLMRequestError(
                "the openai response holds no textual content",
                provider=self.name,
            )
        return content


class AnthropicProvider(_BaseProvider):
    """Provider backed by the Anthropic messages API.

    The Anthropic API has no ``seed`` parameter, so reproducibility is
    obtained by injecting the seed into the prompt itself
    (:meth:`_inject_seed`). The seed is also sent as the
    ``x-aldermere-seed`` header, which makes the request traceable in the
    provider logs without changing the model output.
    """

    name = "anthropic"

    def _default_model(self) -> str:
        """Return the default model of the provider.

        Returns:
            The default model identifier.
        """
        return DEFAULT_ANTHROPIC_MODEL

    def _inject_seed(self, prompt: str) -> str:
        """Add the seed to the prompt.

        The instruction is deterministic and machine-readable, so the model
        receives the very same prompt for the very same seed.

        Args:
            prompt: The user prompt.

        Returns:
            The prompt with the seed instruction appended.
        """
        return (
            f"{prompt}\n\n"
            f"[reproducibility] generation_seed={self.seed}. "
            f"Keep the output stable for this seed."
        )

    def _build_request(self, prompt: str, system: str | None) -> urllib.request.Request:
        """Build the HTTP request of a call.

        Args:
            prompt: The user prompt.
            system: The system prompt, if any.

        Returns:
            The prepared request.
        """
        body = json.dumps(
            {
                "model": self.model,
                "max_tokens": 4096,
                "temperature": self.temperature,
                "system": system or "",
                "messages": [{"role": "user", "content": self._inject_seed(prompt)}],
            },
            ensure_ascii=False,
        ).encode("utf-8")
        request = urllib.request.Request(
            ANTHROPIC_ENDPOINT,
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "x-api-key": self._api_key,
                "anthropic-version": ANTHROPIC_VERSION,
                "x-aldermere-seed": str(self.seed),
            },
        )
        return request

    def _extract_text(self, payload: Mapping[str, Any]) -> str:
        """Extract the answer text out of a response payload.

        Args:
            payload: Decoded response body.

        Returns:
            The answer text.

        Raises:
            LLMRequestError: If the payload has no usable answer.
        """
        blocks = payload.get("content")
        if not isinstance(blocks, list) or not blocks:
            raise LLMRequestError(
                "the anthropic response holds no content blocks",
                provider=self.name,
            )
        parts: list[str] = []
        for block in blocks:
            if not isinstance(block, dict):
                continue
            if block.get("type") != "text":
                continue
            text = block.get("text")
            if isinstance(text, str):
                parts.append(text)
        if not parts:
            raise LLMRequestError(
                "the anthropic response holds no textual content",
                provider=self.name,
            )
        return "".join(parts)


def provider_from_env(
    *,
    model: str | None = None,
    temperature: float = DEFAULT_TEMPERATURE,
    seed: int = 0,
    cache: DiskCache | None = None,
) -> LLMProvider:
    """Build the provider described by the environment.

    The OpenAI key wins when both keys are present, because the pipeline is
    configured for a single backend at a time.

    Args:
        model: Model identifier. Defaults to ``ALDERMERE_LLM_MODEL`` or the
            default of the selected provider.
        temperature: Sampling temperature.
        seed: Seed sent with every request.
        cache: Cache consulted before every request.

    Returns:
        The configured provider.

    Raises:
        LLMNotConfiguredError: If neither API key is present.
    """
    openai_key = os.environ.get(OPENAI_KEY_ENV_VAR, "").strip()
    anthropic_key = os.environ.get(ANTHROPIC_KEY_ENV_VAR, "").strip()

    selected_model = model or os.environ.get(MODEL_ENV_VAR, "").strip()

    if openai_key:
        return OpenAIProvider(
            openai_key,
            model=selected_model or None,
            temperature=temperature,
            seed=seed,
            cache=cache,
        )
    if anthropic_key:
        return AnthropicProvider(
            anthropic_key,
            model=selected_model or None,
            temperature=temperature,
            seed=seed,
            cache=cache,
        )
    raise LLMNotConfiguredError(
        "no LLM provider is configured. Export "
        f"{OPENAI_KEY_ENV_VAR} (OpenAI) or {ANTHROPIC_KEY_ENV_VAR} (Anthropic) "
        "in the environment before running the content pipeline."
    )
