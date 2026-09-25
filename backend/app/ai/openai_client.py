"""
Async OpenAI API wrapper.

Handles:
  - Exponential-backoff retries on timeout / server errors (3× default)
  - 60-second delay + single retry on rate-limit (429)
  - Context-too-long detection (raises ContextTooLongError)
  - Refusal passthrough (caller checks model text)
  - Lazy client instantiation (API key not required at import time)
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Custom exceptions
# ---------------------------------------------------------------------------

class OpenAICallError(RuntimeError):
    """Wraps any unrecoverable OpenAI API error."""


class ContextTooLongError(OpenAICallError):
    """The prompt exceeded the model's context window."""


class RateLimitedError(OpenAICallError):
    """Still rate-limited after retry delay."""


# ---------------------------------------------------------------------------
# Lazy client factory
# ---------------------------------------------------------------------------

_client_cache: dict[str, object] = {}  # keyed by api_key


def _get_client(api_key: str):
    """Return a cached AsyncOpenAI client for the given key."""
    if api_key not in _client_cache:
        try:
            from openai import AsyncOpenAI
        except ImportError as exc:
            raise OpenAICallError(
                "openai package not installed. "
                "Run: pip install 'aci-backend[ai]'"
            ) from exc
        _client_cache[api_key] = AsyncOpenAI(api_key=api_key)
    return _client_cache[api_key]


# ---------------------------------------------------------------------------
# Main call function
# ---------------------------------------------------------------------------

async def call_openai(
    *,
    api_key: str,
    model: str,
    system: str,
    user: str,
    json_mode: bool = False,
    max_tokens: int = 2048,
    timeout_sec: int = 60,
    max_retries: int = 3,
) -> tuple[str, int]:
    """
    Call the OpenAI chat-completions endpoint.

    Returns:
        (content: str, tokens_used: int)

    Raises:
        ContextTooLongError   — prompt too long for the model
        RateLimitedError      — rate-limited and retry exhausted
        OpenAICallError       — any other unrecoverable API error
    """
    try:
        from openai import (
            AsyncOpenAI,
            APITimeoutError,
            RateLimitError,
            BadRequestError,
            APIStatusError,
            APIConnectionError,
        )
    except ImportError as exc:
        raise OpenAICallError(
            "openai package not installed. Run: pip install 'aci-backend[ai]'"
        ) from exc

    client = _get_client(api_key)

    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]

    kwargs: dict = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "timeout": timeout_sec,
    }
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}

    backoff = 10  # seconds between retries
    last_exc: Exception | None = None

    for attempt in range(1, max_retries + 1):
        t0 = time.monotonic()
        try:
            response = await client.chat.completions.create(**kwargs)  # type: ignore[attr-defined]
            content = response.choices[0].message.content or ""
            tokens = response.usage.total_tokens if response.usage else 0
            elapsed_ms = int((time.monotonic() - t0) * 1000)
            logger.debug(
                "OpenAI call ok model=%s tokens=%d elapsed_ms=%d attempt=%d",
                model, tokens, elapsed_ms, attempt,
            )
            return content, tokens

        except BadRequestError as exc:
            # Context window exceeded — do not retry
            if "context_length_exceeded" in str(exc).lower() or \
               "maximum context length" in str(exc).lower():
                raise ContextTooLongError(str(exc)) from exc
            raise OpenAICallError(f"OpenAI bad request: {exc}") from exc

        except RateLimitError as exc:
            logger.warning(
                "OpenAI rate limit on attempt %d/%d — waiting 60 s",
                attempt, max_retries,
            )
            last_exc = exc
            if attempt < max_retries:
                await asyncio.sleep(60)
            continue

        except (APITimeoutError, APIConnectionError) as exc:
            logger.warning(
                "OpenAI timeout/connection error attempt %d/%d: %s",
                attempt, max_retries, exc,
            )
            last_exc = exc
            if attempt < max_retries:
                await asyncio.sleep(backoff * attempt)  # 10 s, 20 s, …
            continue

        except APIStatusError as exc:
            # 5xx server errors — retry
            if exc.status_code and exc.status_code >= 500:
                logger.warning(
                    "OpenAI server error %d attempt %d/%d",
                    exc.status_code, attempt, max_retries,
                )
                last_exc = exc
                if attempt < max_retries:
                    await asyncio.sleep(backoff * attempt)
                continue
            raise OpenAICallError(f"OpenAI API error {exc.status_code}: {exc}") from exc

        except Exception as exc:
            raise OpenAICallError(f"Unexpected OpenAI error: {exc}") from exc

    # All retries exhausted
    if isinstance(last_exc, RateLimitError):
        raise RateLimitedError(
            f"OpenAI rate-limited after {max_retries} attempts"
        ) from last_exc
    raise OpenAICallError(
        f"OpenAI call failed after {max_retries} attempts: {last_exc}"
    ) from last_exc


async def call_openai_streaming(
    *,
    api_key: str,
    model: str,
    system: str,
    user: str,
    json_mode: bool = False,
    max_tokens: int = 2048,
    timeout_sec: int = 60,
):
    """
    Same call as call_openai, but yields raw text deltas as they arrive
    instead of waiting for the full completion — for callers that want to
    start showing/using the response before it's finished generating (see
    textbook_service.generate_next_segment_streaming). No retry logic here
    (unlike call_openai): once a stream has started and partial output may
    already be in front of the caller, transparently retrying from scratch
    isn't safe the way it is for a single non-streaming call — a failure
    mid-stream just propagates, and it's the caller's job to have already
    committed nothing that depended on a clean finish.

    Yields: str chunks (may be empty; never None). The caller should
    accumulate them itself for the final full text.
    """
    try:
        from openai import AsyncOpenAI  # noqa: F401 — import validates the package is installed
    except ImportError as exc:
        raise OpenAICallError(
            "openai package not installed. Run: pip install 'aci-backend[ai]'"
        ) from exc

    client = _get_client(api_key)
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    kwargs: dict = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "timeout": timeout_sec,
        "stream": True,
    }
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}

    stream = await client.chat.completions.create(**kwargs)  # type: ignore[attr-defined]
    async for chunk in stream:
        if not chunk.choices:
            continue
        delta = chunk.choices[0].delta.content
        if delta:
            yield delta


async def call_openai_vision(
    *,
    api_key: str,
    model: str,
    system: str,
    user_text: str,
    image_data: bytes,
    image_media_type: str = "image/jpeg",
    max_tokens: int = 500,
    timeout_sec: int = 60,
    detail: str = "low",
) -> tuple[str, int]:
    """
    Call GPT-4o (or similar) with an image attachment.

    Returns:
        (content: str, tokens_used: int)
    """
    import base64

    try:
        from openai import AsyncOpenAI, BadRequestError, APIStatusError, APITimeoutError, APIConnectionError
    except ImportError as exc:
        raise OpenAICallError("openai package not installed.") from exc

    client = _get_client(api_key)
    b64 = base64.b64encode(image_data).decode()

    messages = [
        {"role": "system", "content": system},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": user_text},
                {"type": "image_url", "image_url": {"url": f"data:{image_media_type};base64,{b64}", "detail": detail}},
            ],
        },
    ]

    try:
        response = await client.chat.completions.create(  # type: ignore[attr-defined]
            model=model,
            messages=messages,
            max_tokens=max_tokens,
            timeout=timeout_sec,
        )
        content = response.choices[0].message.content or ""
        tokens = response.usage.total_tokens if response.usage else 0
        return content, tokens
    except BadRequestError as exc:
        raise OpenAICallError(f"OpenAI vision bad request: {exc}") from exc
    except (APITimeoutError, APIConnectionError, APIStatusError) as exc:
        raise OpenAICallError(f"OpenAI vision error: {exc}") from exc
