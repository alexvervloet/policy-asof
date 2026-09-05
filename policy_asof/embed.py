"""Embeddings, from a local Ollama server or the Voyage API.

There is deliberately no mock provider here. Everywhere else in this project a
keyless fallback is the right call, but phase 2 exists to produce numbers, and a
number computed from a hash of the text is not a smaller version of the truth,
it is a different thing wearing its clothes. If no embedder is reachable the
measurement refuses to run and says so.

Results are cached on disk by (model, text), so re-running a benchmark costs
nothing and two runs of the same corpus produce the same vectors.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import struct
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, cast

PROVIDER = os.environ.get("EMBED_PROVIDER", "ollama")
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("EMBED_MODEL", "nomic-embed-text")
VOYAGE_MODEL = os.environ.get("VOYAGE_MODEL", "voyage-4")
VOYAGE_URL = "https://api.voyageai.com/v1/embeddings"

CACHE = Path(
    os.environ.get("EMBED_CACHE", Path(__file__).resolve().parent.parent / "results" / "embeddings")
)

Vector = list[float]


class EmbedderUnavailable(RuntimeError):
    """Raised instead of falling back to something that would produce numbers."""


def _post(url: str, payload: dict[str, object], headers: dict[str, str]) -> Any:
    # Both endpoints are configurable through the environment, so the scheme is
    # checked rather than assumed. The noqa is for the audit rule that fires on
    # any urlopen of a non-literal URL; the check above is what it asks for.
    if not url.startswith(("http://", "https://")):
        raise EmbedderUnavailable(f"refusing to open a non-http URL: {url}")
    request = urllib.request.Request(  # noqa: S310
        url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", **headers},
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:  # noqa: S310
            return json.loads(response.read())
    except (urllib.error.URLError, TimeoutError) as exc:
        raise EmbedderUnavailable(f"{url}: {exc}") from exc


def _as_vectors(raw: Any, source: str) -> list[Vector]:
    """Everything off the wire is unknown until it is checked, including shape."""
    if not isinstance(raw, list):
        raise EmbedderUnavailable(f"unexpected response from {source}: {raw!r:.120}")
    # The two checkers disagree about what the isinstance above proved. mypy
    # narrows to list[Any] and calls the cast redundant; pyright narrows to
    # list[Unknown] and requires it under strict. There is no spelling both
    # accept, so the cast is written for pyright and mypy is told about it on
    # this line only.
    rows = cast("list[Any]", raw)  # type: ignore[redundant-cast]
    vectors: list[Vector] = []
    for row in rows:
        values = cast("list[Any]", row)
        vectors.append([float(value) for value in values])
    return vectors


def model_name() -> str:
    return OLLAMA_MODEL if PROVIDER == "ollama" else VOYAGE_MODEL


def _embed_ollama(texts: list[str], input_type: str | None) -> list[Vector]:
    del input_type  # Ollama has no asymmetric hint; the parameter is ignored.
    body = _post(f"{OLLAMA_URL}/api/embed", {"model": OLLAMA_MODEL, "input": texts}, {})
    return _as_vectors(body.get("embeddings"), "Ollama")


def _embed_voyage(texts: list[str], input_type: str | None) -> list[Vector]:
    key = os.environ.get("VOYAGE_API_KEY")
    if not key:
        raise EmbedderUnavailable("EMBED_PROVIDER=voyage but VOYAGE_API_KEY is not set")
    payload: dict[str, object] = {"model": VOYAGE_MODEL, "input": texts}
    if input_type:
        payload["input_type"] = input_type
    body = _post(VOYAGE_URL, payload, {"Authorization": f"Bearer {key}"})
    data = body.get("data")
    if not isinstance(data, list):
        raise EmbedderUnavailable(f"unexpected response from Voyage: {body!r:.120}")
    # Voyage tags each embedding with its input index. Sort, rather than trust
    # the order the list happens to arrive in.
    items = cast("list[dict[str, Any]]", data)
    ordered = sorted(items, key=lambda item: int(item["index"]))
    return _as_vectors([item["embedding"] for item in ordered], "Voyage")


def _cache_path(text: str) -> Path:
    digest = hashlib.sha256(f"{PROVIDER}:{model_name()}:{text}".encode()).hexdigest()
    # The extension names the on-disk format. Vectors were briefly stored as
    # 32-bit floats, which meant a warm cache and a cold one produced slightly
    # different numbers for the same benchmark, and a file written in one format
    # and read in the other unpacks to the wrong length without erroring.
    return CACHE / digest[:2] / f"{digest}.f64"


def _read_cache(text: str) -> Vector | None:
    path = _cache_path(text)
    if not path.exists():
        return None
    raw = path.read_bytes()
    return list(struct.unpack(f"{len(raw) // 8}d", raw))


def _write_cache(text: str, vector: Vector) -> None:
    path = _cache_path(text)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(struct.pack(f"{len(vector)}d", *vector))


def embed(texts: list[str], input_type: str | None = None) -> list[Vector]:
    """Embed every text, reading from the cache and filling what is missing."""
    vectors: dict[int, Vector] = {}
    missing: list[tuple[int, str]] = []
    for index, text in enumerate(texts):
        cached = _read_cache(text)
        if cached is None:
            missing.append((index, text))
        else:
            vectors[index] = cached

    if missing:
        provider = {"ollama": _embed_ollama, "voyage": _embed_voyage}.get(PROVIDER)
        if provider is None:
            raise EmbedderUnavailable(f"unknown EMBED_PROVIDER {PROVIDER!r}")
        computed = provider([text for _, text in missing], input_type)
        for (index, text), vector in zip(missing, computed, strict=True):
            _write_cache(text, vector)
            vectors[index] = vector

    return [vectors[index] for index in range(len(texts))]


def cosine(left: Vector, right: Vector) -> float:
    dot = 0.0
    left_square = 0.0
    right_square = 0.0
    for a, b in zip(left, right, strict=True):
        dot += a * b
        left_square += a * a
        right_square += b * b
    if left_square == 0.0 or right_square == 0.0:
        return 0.0
    return dot / (math.sqrt(left_square) * math.sqrt(right_square))
