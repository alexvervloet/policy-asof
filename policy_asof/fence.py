"""Mark where untrusted text starts and stops.

Everything a document carries is attacker-controlled in a system where documents
are uploaded: the clause text, the title, the section number, and the dates
printed inside the prose. None of it may reach the model looking like an
instruction, and none of it may close the region it is wrapped in.

Three decisions, each of them a bug somebody else already paid for.

**The marker carries a per-request nonce.** A fixed delimiter is one an attacker
can simply type. A document written today and retrieved next week cannot contain
a value that did not exist when it was written.

**Marker-shaped text is replaced, not deleted.** `str.replace` is one
left-to-right pass, so removing an occurrence closes the gap and the text either
side can spell the marker that was just removed. The replacement contains no
angle bracket, so the two halves are never adjacent and one pass is provably
enough. It also keeps the forgery visible, where deleting would quietly erase
the evidence that somebody tried.

**Matching folds, replacing does not.** Homoglyphs and invisible characters make
`<<</untrusted:` readable to a model and invisible to a byte-for-byte regex, so
the search runs over folded text. The fold keeps an index back to the original,
because handing the model a folded document would silently rewrite content, and
handing an incident review a folded document answers "what did it actually say"
by destroying the evidence.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

# One-for-one substitutions and pure deletions only. Anything that changes a
# character's length would make the index map approximate, and an approximate
# map means replacing the wrong bytes.
HOMOGLYPHS = {
    "А": "A",
    "В": "B",
    "Е": "E",
    "К": "K",
    "М": "M",
    "Н": "H",
    "О": "O",
    "Р": "P",
    "С": "C",
    "Т": "T",
    "У": "Y",
    "Х": "X",
    "а": "a",
    "е": "e",
    "о": "o",
    "р": "p",
    "с": "c",
    "у": "y",
    "х": "x",
    "і": "i",
    "ԁ": "d",
    "ͼ": "s",
    "ο": "o",
    "Α": "A",
    "Β": "B",
    "Ε": "E",
    "Κ": "K",
    "Μ": "M",
    "Ν": "N",
    "Ο": "O",
    "Ρ": "P",
    "Τ": "T",
    "Χ": "X",
    "＜": "<",
    "＞": ">",
    "：": ":",
    "／": "/",
}

INVISIBLE = {
    "​",
    "‌",
    "‍",
    "‎",
    "‏",
    "⁠",
    "﻿",
    "­",
    "͏",
    "؜",
    "᠎",
}

MARKER = re.compile(r"<<<\s*/?\s*untrusted\s*:[^>]{0,64}>>>", re.IGNORECASE)

# No angle bracket, so the halves either side of a removal can never spell a
# marker between them.
REDACTED = "[marker removed]"


@dataclass(frozen=True)
class Fold:
    text: str
    origin: tuple[int, ...]

    def span(self, start: int, end: int) -> tuple[int, int]:
        """A span in folded coordinates, back in the original's."""
        if start >= len(self.origin):
            return len(self.origin), len(self.origin)
        first = self.origin[start]
        last = self.origin[end - 1] + 1 if end > start else first
        return first, last


def fold(text: str) -> Fold:
    """Normalise lookalikes for matching, keeping the way back."""
    folded: list[str] = []
    origin: list[int] = []
    for position, character in enumerate(text):
        if character in INVISIBLE:
            continue
        folded.append(HOMOGLYPHS.get(character, character))
        origin.append(position)
    return Fold("".join(folded), tuple(origin))


def neutralise(text: str) -> str:
    """Replace anything marker-shaped, on the original bytes."""
    folded = fold(text)
    spans = [folded.span(match.start(), match.end()) for match in MARKER.finditer(folded.text)]
    if not spans:
        return text
    out: list[str] = []
    cursor = 0
    for start, end in spans:
        out.append(text[cursor:start])
        out.append(REDACTED)
        cursor = end
    out.append(text[cursor:])
    return "".join(out)


def token(request_id: str) -> str:
    return hashlib.sha256(f"policy-asof-fence:{request_id}".encode()).hexdigest()[:16]


def tags(request_id: str) -> tuple[str, str]:
    stamp = token(request_id)
    return f"<<<untrusted:{stamp}>>>", f"<<</untrusted:{stamp}>>>"


def wrap(request_id: str, fields: dict[str, str]) -> str:
    """Fence one passage, every field of it.

    A struct is not one attacker-controlled field, it is all of them. The title
    and the section number arrive from the same upload as the text, so they are
    neutralised too rather than interpolated a line above the fence.
    """
    opener, closer = tags(request_id)
    lines = [opener]
    for name, value in fields.items():
        lines.append(f"{neutralise(name)}: {neutralise(value)}")
    lines.append(closer)
    return "\n".join(lines)
