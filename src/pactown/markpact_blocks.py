from __future__ import annotations

import re
from dataclasses import dataclass

CODEBLOCK_RE = re.compile(
    r"^```(?:(?P<lang>[^\s]+)\s+)?markpact:(?P<kind>\w+)(?:\s+(?P<meta>[^\n]+))?\n(?P<body>.*?)\n^```[ \t]*$",
    re.DOTALL | re.MULTILINE,
)


@dataclass
class Block:
    kind: str
    meta: str
    body: str
    lang: str = ""

    def get_path(self) -> str | None:
        m = re.search(r"\bpath=(\S+)", self.meta)
        return m[1] if m else None


def parse_blocks(text: str) -> list[Block]:
    return [
        Block(
            kind=m.group("kind"),
            meta=(m.group("meta") or "").strip(),
            body=m.group("body").strip(),
            lang=(m.group("lang") or "").strip(),
        )
        for m in CODEBLOCK_RE.finditer(text)
    ]
