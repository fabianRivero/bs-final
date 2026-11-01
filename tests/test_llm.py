"""Tests for the abstracted LLM client.

What is under test
------------------
The client is the only place where the project talks to a language model, so
it has to be predictable: a cache hit must skip the network entirely, the
cache key must change when the request changes, and a failure must never
leak the API key.

No test in this module touches the network: the HTTP layer is replaced by a
stub, and the environment is manipulated explicitly.
"""

from __future__ import annotations

import hashlib
import json
import urllib.error
from pathlib import Path
from typing import Any

import pytest

from content.llm import (
    CACHE_DIR,
    DEFAULT_ANTHROPIC_MODEL,
    DEFAULT_OPENAI_MODEL,
    AnthropicProvider,
    DiskCache,
    LLMNotConfiguredError,
    LLMRequestError,
    OpenAIProvider,
    cache_key,
    provider_from_env,
)


class _FakeResponse:
    """A stand-in for the object returned by ``urlopen``.

    Attributes:
        payload: The bytes returned by the fake response.
    """

    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def read(self) -> bytes:
        """Return the payload of the response.

        Returns:
            The raw bytes.
        """
        return self._payload

    def __enter__(self) -> _FakeResponse:
        """Enter the context manager.

        Returns:
            The response itself.
        """
        return self

    def __exit__(self, *args: object) -> None:
        """Leave the context manager.

        Args:
            *args: Ignored exception information.
        """
        return None


@pytest.fixture(autouse=True)
def _clean_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove the API keys and the model variable from the environment.

    Args:
        monkeypatch: The pytest monkeypatch fixture.
    """
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ALDERMERE_LLM_MODEL", raising=False)


@pytest.fixture
def cache(tmp_path: Path) -> DiskCache:
    """Return a cache rooted in a temporary directory.

    Args:
        tmp_path: The temporary directory of the test.

    Returns:
        The cache.
    """
    return DiskCache(tmp_path / "llm")


def _patch_urlopen(
    monkeypatch: pytest.MonkeyPatch,
    handler: Any,
) -> list[Any]:
    """Replace ``urllib.request.urlopen`` with a stub.

    Args:
        monkeypatch: The pytest monkeypatch fixture.
        handler: Callable that receives the request and returns the raw body.

    Returns:
        The list that records the requests the stub received.
    """
    seen: list[Any] = []

    def _fake_urlopen(request: Any, timeout: float | None = None) -> _FakeResponse:
        seen.append(request)
        return _FakeResponse(handler(request))

    monkeypatch.setattr("urllib.request.urlopen", _fake_urlopen)
    return seen


# ----------------------------------------------------------------------
# Cache key
# ----------------------------------------------------------------------


def test_cache_key_is_stable() -> None:
    """The same request always maps to the same key."""
    first = cache_key("prompt", "system", "model", 0.7, 42)
    second = cache_key("prompt", "system", "model", 0.7, 42)
    assert first == second


def test_cache_key_changes_with_the_seed() -> None:
    """The seed takes part in the key, so a new seed is a new answer."""
    first = cache_key("prompt", "system", "model", 0.7, 42)
    second = cache_key("prompt", "system", "model", 0.7, 43)
    assert first != second


def test_cache_key_changes_with_the_prompt() -> None:
    """A different prompt is a different answer."""
    first = cache_key("prompt", "system", "model", 0.7, 42)
    second = cache_key("other prompt", "system", "model", 0.7, 42)
    assert first != second


def test_cache_key_changes_with_the_system_prompt() -> None:
    """A different system prompt is a different answer."""
    first = cache_key("prompt", "system", "model", 0.7, 42)
    second = cache_key("prompt", "other", "model", 0.7, 42)
    assert first != second


def test_cache_key_changes_with_the_model() -> None:
    """A different model is a different answer."""
    first = cache_key("prompt", "system", "model", 0.7, 42)
    second = cache_key("prompt", "system", "other", 0.7, 42)
    assert first != second


def test_cache_key_changes_with_the_temperature() -> None:
    """A different temperature is a different answer."""
    first = cache_key("prompt", "system", "model", 0.7, 42)
    second = cache_key("prompt", "system", "model", 0.1, 42)
    assert first != second


def test_cache_key_is_a_sha256_digest() -> None:
    """The key is a hexadecimal sha256 digest."""
    key = cache_key("prompt", None, "model", 0.7, 42)
    assert len(key) == 64
    assert set(key) <= set("0123456789abcdef")


# ----------------------------------------------------------------------
# Disk cache
# ----------------------------------------------------------------------


def test_disk_cache_miss_returns_none(cache: DiskCache) -> None:
    """An empty cache has nothing to offer."""
    assert cache.get("deadbeef") is None


def test_disk_cache_roundtrip(cache: DiskCache) -> None:
    """A cached answer is read back unchanged."""
    from content.llm import LLMResponse

    response = LLMResponse(
        text="hello",
        model="a-model",
        provider="fake",
        seed=7,
        temperature=0.7,
    )
    path = cache.put("key", response)
    assert path.is_file()
    cached = cache.get("key")
    assert cached is not None
    assert cached.text == "hello"
    assert cached.model == "a-model"
    assert cached.cached is True


def test_disk_cache_ignores_a_corrupted_entry(cache: DiskCache) -> None:
    """A corrupted cache entry is a miss, not a crash."""
    path = cache.path_for("key")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not json", encoding="utf-8")
    assert cache.get("key") is None


def test_disk_cache_uses_the_documented_layout(cache: DiskCache) -> None:
    """The entry lives in a file named after the key."""
    from content.llm import LLMResponse

    key = cache_key("prompt", None, "model", 0.7, 1)
    cache.put(key, LLMResponse(text="x", model="m", provider="p", seed=1, temperature=0.7))
    assert cache.path_for(key).name == f"{key}.json"


def test_default_cache_directory_is_inside_the_project() -> None:
    """The default cache lives in the project, not in a temporary folder."""
    assert CACHE_DIR.name == "llm"
    assert CACHE_DIR.parent.name == ".cache"
    assert (CACHE_DIR.parent.parent / "pyproject.toml").is_file()


# ----------------------------------------------------------------------
# Providers
# ----------------------------------------------------------------------


def test_openai_provider_uses_the_default_model(cache: DiskCache) -> None:
    """The provider falls back to its default model."""
    provider = OpenAIProvider("key", cache=cache)
    assert provider.model == DEFAULT_OPENAI_MODEL


def test_openai_provider_reads_the_model_from_the_environment(
    monkeypatch: pytest.MonkeyPatch,
    cache: DiskCache,
) -> None:
    """The model is configurable through the environment."""
    monkeypatch.setenv("OPENAI_API_KEY", "key")
    monkeypatch.setenv("ALDERMERE_LLM_MODEL", "gpt-4o")
    provider = provider_from_env(cache=cache)
    assert isinstance(provider, OpenAIProvider)
    assert provider.model == "gpt-4o"


def test_openai_provider_sends_the_seed_and_the_temperature(
    monkeypatch: pytest.MonkeyPatch,
    cache: DiskCache,
) -> None:
    """The request carries the seed and the temperature."""
    seen = _patch_urlopen(
        monkeypatch,
        lambda request: json.dumps({"choices": [{"message": {"content": "ok"}}]}).encode(),
    )
    provider = OpenAIProvider("key", cache=cache, seed=99, temperature=0.3)
    provider.complete("hello")
    body = json.loads(seen[0].data.decode("utf-8"))
    assert body["seed"] == 99
    assert body["temperature"] == 0.3
    assert body["model"] == DEFAULT_OPENAI_MODEL


def test_openai_provider_sends_the_api_key_in_the_header(
    monkeypatch: pytest.MonkeyPatch,
    cache: DiskCache,
) -> None:
    """The key travels in the Authorization header."""
    seen = _patch_urlopen(
        monkeypatch,
        lambda request: json.dumps({"choices": [{"message": {"content": "ok"}}]}).encode(),
    )
    provider = OpenAIProvider("secret-key", cache=cache)
    provider.complete("hello")
    assert seen[0].get_header("Authorization") == "Bearer secret-key"


def test_openai_provider_reads_the_answer(
    monkeypatch: pytest.MonkeyPatch,
    cache: DiskCache,
) -> None:
    """The textual answer is extracted from the response."""
    _patch_urlopen(
        monkeypatch,
        lambda request: json.dumps({"choices": [{"message": {"content": "the answer"}}]}).encode(),
    )
    provider = OpenAIProvider("key", cache=cache)
    assert provider.complete("hello") == "the answer"


def test_anthropic_provider_uses_the_default_model(cache: DiskCache) -> None:
    """The provider falls back to its default model."""
    provider = AnthropicProvider("key", cache=cache)
    assert provider.model == DEFAULT_ANTHROPIC_MODEL


def test_anthropic_provider_sends_the_seed_in_the_prompt_and_the_header(
    monkeypatch: pytest.MonkeyPatch,
    cache: DiskCache,
) -> None:
    """The Anthropic API has no seed parameter, so it travels in the request."""
    seen = _patch_urlopen(
        monkeypatch,
        lambda request: json.dumps({"content": [{"type": "text", "text": "ok"}]}).encode(),
    )
    provider = AnthropicProvider("key", cache=cache, seed=1234)
    provider.complete("hello")
    body = json.loads(seen[0].data.decode("utf-8"))
    assert "generation_seed=1234" in body["messages"][0]["content"]
    assert seen[0].get_header("X-aldermere-seed") == "1234"


def test_anthropic_provider_sends_the_version_header(
    monkeypatch: pytest.MonkeyPatch,
    cache: DiskCache,
) -> None:
    """The Anthropic API version header is sent."""
    seen = _patch_urlopen(
        monkeypatch,
        lambda request: json.dumps({"content": [{"type": "text", "text": "ok"}]}).encode(),
    )
    provider = AnthropicProvider("key", cache=cache)
    provider.complete("hello")
    assert seen[0].get_header("Anthropic-version") == "2023-06-01"


def test_anthropic_provider_reads_the_answer(
    monkeypatch: pytest.MonkeyPatch,
    cache: DiskCache,
) -> None:
    """The textual answer is extracted from the response."""
    _patch_urlopen(
        monkeypatch,
        lambda request: json.dumps({"content": [{"type": "text", "text": "the answer"}]}).encode(),
    )
    provider = AnthropicProvider("key", cache=cache)
    assert provider.complete("hello") == "the answer"


def test_a_provider_without_a_key_is_rejected(cache: DiskCache) -> None:
    """A provider without a key cannot be built."""
    with pytest.raises(LLMNotConfiguredError):
        OpenAIProvider("", cache=cache)


# ----------------------------------------------------------------------
# Caching behaviour
# ----------------------------------------------------------------------


def test_the_second_call_is_served_from_the_cache(
    monkeypatch: pytest.MonkeyPatch,
    cache: DiskCache,
) -> None:
    """A cache hit skips the API call entirely."""
    calls = {"count": 0}

    def _handler(request: Any) -> bytes:
        calls["count"] += 1
        return json.dumps({"choices": [{"message": {"content": "cached"}}]}).encode()

    _patch_urlopen(monkeypatch, _handler)
    provider = OpenAIProvider("key", cache=cache)
    first = provider.complete("hello")
    second = provider.complete("hello")
    assert first == second == "cached"
    assert calls["count"] == 1


def test_a_different_seed_does_not_reuse_the_cache(
    monkeypatch: pytest.MonkeyPatch,
    cache: DiskCache,
) -> None:
    """The seed is part of the key, so a new seed reaches the API."""
    calls = {"count": 0}

    def _handler(request: Any) -> bytes:
        calls["count"] += 1
        answer = f"answer {calls['count']}"
        return json.dumps({"choices": [{"message": {"content": answer}}]}).encode()

    _patch_urlopen(monkeypatch, _handler)
    first = OpenAIProvider("key", cache=cache, seed=1).complete("hello")
    second = OpenAIProvider("key", cache=cache, seed=2).complete("hello")
    assert first == "answer 1"
    assert second == "answer 2"
    assert calls["count"] == 2


def test_a_different_prompt_does_not_reuse_the_cache(
    monkeypatch: pytest.MonkeyPatch,
    cache: DiskCache,
) -> None:
    """A different prompt reaches the API."""
    calls = {"count": 0}

    def _handler(request: Any) -> bytes:
        calls["count"] += 1
        return json.dumps({"choices": [{"message": {"content": "ok"}}]}).encode()

    _patch_urlopen(monkeypatch, _handler)
    provider = OpenAIProvider("key", cache=cache)
    provider.complete("hello")
    provider.complete("goodbye")
    assert calls["count"] == 2


def test_the_cache_entry_holds_the_answer(
    monkeypatch: pytest.MonkeyPatch,
    cache: DiskCache,
) -> None:
    """The entry on disk holds the answer and its metadata."""
    _patch_urlopen(
        monkeypatch,
        lambda request: json.dumps({"choices": [{"message": {"content": "stored"}}]}).encode(),
    )
    provider = OpenAIProvider("key", cache=cache, seed=5)
    provider.complete("hello")
    key = cache_key("hello", None, provider.model, provider.temperature, 5)
    document = json.loads(cache.path_for(key).read_text(encoding="utf-8"))
    assert document["text"] == "stored"
    assert document["seed"] == 5
    assert document["model"] == provider.model


# ----------------------------------------------------------------------
# Errors
# ----------------------------------------------------------------------


def test_a_request_error_carries_the_status_code(
    monkeypatch: pytest.MonkeyPatch,
    cache: DiskCache,
) -> None:
    """The HTTP status code of a failure is reported."""

    def _handler(request: Any) -> bytes:
        raise urllib.error.HTTPError(
            url="https://example.invalid",
            code=429,
            msg="Too Many Requests",
            hdrs=None,
            fp=None,
        )

    _patch_urlopen(monkeypatch, _handler)
    provider = OpenAIProvider("key", cache=cache)
    with pytest.raises(LLMRequestError) as error:
        provider.complete("hello")
    assert error.value.status_code == 429


def test_a_request_error_does_not_leak_the_api_key(
    monkeypatch: pytest.MonkeyPatch,
    cache: DiskCache,
) -> None:
    """A failure never puts the key in the message."""

    def _handler(request: Any) -> bytes:
        raise urllib.error.HTTPError(
            url="https://example.invalid",
            code=401,
            msg="Unauthorized",
            hdrs=None,
            fp=None,
        )

    _patch_urlopen(monkeypatch, _handler)
    provider = OpenAIProvider("sk-super-secret-value", cache=cache)
    with pytest.raises(LLMRequestError) as error:
        provider.complete("hello")
    assert "sk-super-secret-value" not in str(error.value)


def test_a_request_error_sanitises_a_body_that_echoes_the_key(
    monkeypatch: pytest.MonkeyPatch,
    cache: DiskCache,
) -> None:
    """A body that contains the key is redacted."""

    def _handler(request: Any) -> bytes:
        body = b'{"error": {"message": "invalid key sk-super-secret-value"}}'
        raise urllib.error.HTTPError(
            url="https://example.invalid",
            code=400,
            msg="Bad Request",
            hdrs=None,
            fp=io_bytes(body),
        )

    _patch_urlopen(monkeypatch, _handler)
    provider = OpenAIProvider("sk-super-secret-value", cache=cache)
    with pytest.raises(LLMRequestError) as error:
        provider.complete("hello")
    assert "sk-super-secret-value" not in str(error.value)
    assert "<redacted>" in str(error.value)


def test_a_network_error_is_reported(
    monkeypatch: pytest.MonkeyPatch,
    cache: DiskCache,
) -> None:
    """A connection failure is reported as a request error."""

    def _handler(request: Any) -> bytes:
        raise urllib.error.URLError("no route to host")

    _patch_urlopen(monkeypatch, _handler)
    provider = OpenAIProvider("key", cache=cache)
    with pytest.raises(LLMRequestError, match="no route to host"):
        provider.complete("hello")


def test_a_malformed_body_is_reported(
    monkeypatch: pytest.MonkeyPatch,
    cache: DiskCache,
) -> None:
    """A body that is not JSON is reported as a request error."""
    _patch_urlopen(monkeypatch, lambda request: b"not json at all")
    provider = OpenAIProvider("key", cache=cache)
    with pytest.raises(LLMRequestError, match="not valid JSON"):
        provider.complete("hello")


def test_an_answer_without_choices_is_reported(
    monkeypatch: pytest.MonkeyPatch,
    cache: DiskCache,
) -> None:
    """A response without an answer is reported as a request error."""
    _patch_urlopen(monkeypatch, lambda request: json.dumps({"choices": []}).encode())
    provider = OpenAIProvider("key", cache=cache)
    with pytest.raises(LLMRequestError, match="no choices"):
        provider.complete("hello")


def test_an_anthropic_answer_without_content_is_reported(
    monkeypatch: pytest.MonkeyPatch,
    cache: DiskCache,
) -> None:
    """A response without content blocks is reported as a request error."""
    _patch_urlopen(monkeypatch, lambda request: json.dumps({"content": []}).encode())
    provider = AnthropicProvider("key", cache=cache)
    with pytest.raises(LLMRequestError, match="no content blocks"):
        provider.complete("hello")


# ----------------------------------------------------------------------
# Provider selection
# ----------------------------------------------------------------------


def test_provider_from_env_without_any_key_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """Without a key there is no provider to build."""
    with pytest.raises(LLMNotConfiguredError) as error:
        provider_from_env()
    assert "OPENAI_API_KEY" in str(error.value)
    assert "ANTHROPIC_API_KEY" in str(error.value)


def test_provider_from_env_selects_openai(
    monkeypatch: pytest.MonkeyPatch,
    cache: DiskCache,
) -> None:
    """The OpenAI key selects the OpenAI provider."""
    monkeypatch.setenv("OPENAI_API_KEY", "key")
    provider = provider_from_env(cache=cache)
    assert isinstance(provider, OpenAIProvider)
    assert provider.name == "openai"


def test_provider_from_env_selects_anthropic(
    monkeypatch: pytest.MonkeyPatch,
    cache: DiskCache,
) -> None:
    """The Anthropic key selects the Anthropic provider."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "key")
    provider = provider_from_env(cache=cache)
    assert isinstance(provider, AnthropicProvider)
    assert provider.name == "anthropic"


def test_provider_from_env_prefers_openai_when_both_keys_are_present(
    monkeypatch: pytest.MonkeyPatch,
    cache: DiskCache,
) -> None:
    """The pipeline is configured for one backend at a time."""
    monkeypatch.setenv("OPENAI_API_KEY", "key")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "key")
    provider = provider_from_env(cache=cache)
    assert isinstance(provider, OpenAIProvider)


def test_provider_from_env_ignores_a_blank_key(
    monkeypatch: pytest.MonkeyPatch,
    cache: DiskCache,
) -> None:
    """A blank key is not a key."""
    monkeypatch.setenv("OPENAI_API_KEY", "   ")
    with pytest.raises(LLMNotConfiguredError):
        provider_from_env(cache=cache)


def test_provider_from_env_forwards_the_seed_and_the_temperature(
    monkeypatch: pytest.MonkeyPatch,
    cache: DiskCache,
) -> None:
    """The seed and the temperature reach the provider."""
    monkeypatch.setenv("OPENAI_API_KEY", "key")
    provider = provider_from_env(seed=77, temperature=0.2, cache=cache)
    assert provider.seed == 77
    assert provider.temperature == 0.2


def test_the_cache_key_of_a_provider_matches_the_documented_one(
    monkeypatch: pytest.MonkeyPatch,
    cache: DiskCache,
) -> None:
    """The provider computes the very same key the helper computes."""
    monkeypatch.setenv("OPENAI_API_KEY", "key")
    provider = provider_from_env(seed=3, temperature=0.5, cache=cache)
    expected = hashlib.sha256(
        json.dumps(
            {
                "prompt": "p",
                "system": "",
                "model": provider.model,
                "temperature": 0.5,
                "seed": 3,
            },
            sort_keys=True,
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()
    assert cache_key("p", None, provider.model, 0.5, 3) == expected


def io_bytes(payload: bytes) -> Any:
    """Build a file-like object over a byte string.

    Args:
        payload: The bytes to serve.

    Returns:
        The file-like object.
    """
    import io

    return io.BytesIO(payload)
