"""Where the words come from.

Three providers and one rule: when the configured one is not available, say so
loudly and degrade to the scripted one rather than pretending. A quiet fallback
turns "the model is down" into "the answers got worse for reasons nobody can
reconstruct". `PROVIDER_STRICT=1` turns the fallback into an error for anyone
who would rather fail than degrade.

The scripted provider is deliberately mediocre. It exists so the eval suite can
assert on structure without a model in the loop, and a scripted provider good
enough to hide a real failure would be worse than none. It quotes the first
fenced passage and cites it, which is enough to check that citations are bound
and that two versions never appear together, and not enough to be mistaken for
an answer.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from typing import Any, Protocol

PROVIDER = os.environ.get("ANSWER_PROVIDER", "ollama")
STRICT = os.environ.get("PROVIDER_STRICT") == "1"
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("ANSWER_MODEL", "qwen3:8b")


class ProviderUnavailable(RuntimeError):
    pass


class Provider(Protocol):
    name: str

    def complete(self, system: str, user: str) -> str: ...


class Scripted:
    """Deterministic, keyless, and not trying to be good."""

    name = "scripted"

    def complete(self, system: str, user: str) -> str:
        del system
        passages = _fenced_passages(user)
        if not passages:
            return "I have nothing on record for that date."
        section, text = passages[0]
        first_sentence = text.split(". ")[0].strip().rstrip(".")
        return f"{first_sentence}. (section {section})"


class Ollama:
    name = OLLAMA_MODEL

    def complete(self, system: str, user: str) -> str:
        payload = {
            "model": OLLAMA_MODEL,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "stream": False,
            "think": False,
            "options": {"temperature": 0},
        }
        if not OLLAMA_URL.startswith(("http://", "https://")):
            raise ProviderUnavailable(f"refusing to open a non-http URL: {OLLAMA_URL}")
        request = urllib.request.Request(  # noqa: S310
            f"{OLLAMA_URL}/api/chat",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=300) as response:  # noqa: S310
                body: Any = json.loads(response.read())
        except (urllib.error.URLError, TimeoutError) as exc:
            raise ProviderUnavailable(f"{OLLAMA_URL}: {exc}") from exc
        message = body.get("message", {})
        content = message.get("content")
        if not isinstance(content, str):
            raise ProviderUnavailable(f"unexpected response from Ollama: {body!r:.120}")
        return content.strip()


def _fenced_passages(user: str) -> list[tuple[str, str]]:
    """Pull (section, text) out of the fenced region, for the scripted provider."""
    passages: list[tuple[str, str]] = []
    section = ""
    for line in user.splitlines():
        if line.startswith("section: "):
            section = line.removeprefix("section: ").strip()
        elif line.startswith("text: "):
            passages.append((section, line.removeprefix("text: ").strip()))
    return passages


def choose() -> Provider:
    if PROVIDER == "scripted":
        return Scripted()
    if PROVIDER != "ollama":
        raise ProviderUnavailable(f"unknown ANSWER_PROVIDER {PROVIDER!r}")

    candidate = Ollama()
    try:
        candidate.complete("You are a health check.", "Reply with the word ok.")
    except ProviderUnavailable as exc:
        if STRICT:
            raise
        print(
            "\n"
            "  ========================================================\n"
            f"  FALLBACK: {PROVIDER} ({OLLAMA_MODEL}) is not reachable.\n"
            f"  {exc}\n"
            "  Answering with the scripted provider, which is not a model\n"
            "  and is not trying to be one. Any numbers produced in this\n"
            "  state describe the script, not a system.\n"
            "  Set PROVIDER_STRICT=1 to fail instead.\n"
            "  ========================================================\n",
            file=sys.stderr,
        )
        return Scripted()
    return candidate
