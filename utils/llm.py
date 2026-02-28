"""OpenAI API wrapper — synchronous, with rate-limit-aware retry logic."""
from __future__ import annotations

import time
import json
from typing import Any

from openai import OpenAI, RateLimitError, APIStatusError


def _client(api_key: str) -> OpenAI:
    return OpenAI(api_key=api_key)


def chat_completion(
    messages: list[dict],
    model: str,
    api_key: str,
    *,
    response_format: dict | None = None,
    temperature: float = 0.2,
    max_retries: int = 6,
) -> str:
    """
    Return the text content of the first choice.

    Retry strategy:
    - RateLimitError (429): exponential back-off starting at 5 s, up to max_retries times.
      When many workers run in parallel, a few 429s are expected and handled silently.
    - Other transient errors: exponential back-off starting at 2 s.
    - Non-retryable errors (4xx except 429): re-raise immediately.
    """
    client = _client(api_key)
    kwargs: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
    }
    if response_format:
        kwargs["response_format"] = response_format

    for attempt in range(max_retries):
        try:
            resp = client.chat.completions.create(**kwargs)
            return resp.choices[0].message.content or ""

        except RateLimitError:
            if attempt == max_retries - 1:
                raise
            # Exponential back-off: 5, 10, 20, 40, 80 s
            wait = 5 * (2 ** attempt)
            time.sleep(wait)

        except APIStatusError as e:
            # 4xx errors other than 429 are not retryable
            if e.status_code < 500 and e.status_code != 429:
                raise
            if attempt == max_retries - 1:
                raise
            wait = 2 * (2 ** attempt)
            time.sleep(wait)

        except Exception:
            if attempt == max_retries - 1:
                raise
            wait = 2 * (2 ** attempt)
            time.sleep(wait)

    return ""


def chat_completion_json(
    messages: list[dict],
    model: str,
    api_key: str,
    **kwargs,
) -> dict:
    """Like chat_completion but parses the result as JSON."""
    raw = chat_completion(
        messages,
        model,
        api_key,
        response_format={"type": "json_object"},
        **kwargs,
    )
    return json.loads(raw)


def get_embeddings(
    texts: list[str], api_key: str, model: str = "text-embedding-3-small"
) -> list[list[float]]:
    """Return a list of embedding vectors, one per input text."""
    if not texts:
        return []
    client = _client(api_key)
    all_embeddings: list[list[float]] = []
    chunk_size = 512
    for i in range(0, len(texts), chunk_size):
        chunk = texts[i : i + chunk_size]
        resp = client.embeddings.create(model=model, input=chunk)
        all_embeddings.extend([item.embedding for item in resp.data])
    return all_embeddings
