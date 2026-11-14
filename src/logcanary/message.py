"""Canary message format.

Standard library only: this module also runs inside the host under test.

A canary is one log message:

    lc1 run=<hex> src=<path> seq=<n> ts=<host clock ns> kind=<kind> |<body>| crc=<crc32 hex>

The header comes first so a reconciler can still identify a message whose tail was cut or
mangled. The CRC covers every byte before " crc=", so any change to the body is detected.
The body is plain text, not JSON, because JSON cannot carry a raw newline or tab and a cut
JSON object says nothing about where the damage starts.
"""

from __future__ import annotations

import re
import zlib

KINDS = ("plain", "multiline", "unicode", "control", "long")

HEAD_RE = re.compile(
    r"lc1 run=(?P<run>[0-9a-f]+) src=(?P<src>[a-z]+) seq=(?P<seq>\d+) ts=(?P<ts>-?\d+) kind=(?P<kind>[a-z]+) \|"
)
CRC_RE = re.compile(r" crc=([0-9a-f]{8})\s*$")
# rsyslog escapes control characters on receive as '#' plus three octal digits (#012 = newline).
RSYSLOG_ESC_RE = re.compile(r"#([0-3][0-7]{2})")

_PLAIN = "abcdefghijklmnopqrstuvwxyz0123456789"
_TRACE = [
    "java.lang.IllegalStateException: canary failure for test",
    "\tat com.example.billing.Invoice.post(Invoice.java:214)",
    "\tat com.example.billing.Ledger.apply(Ledger.java:88)",
    "\tat java.base/java.lang.Thread.run(Thread.java:1583)",
]
# Accents, a combining mark, CJK, Arabic and Hebrew (right to left), an emoji, a zero width
# space and a non-breaking space.
_UNICODE = "naïve café é 日本語のログ العربية עברית 🙂🔥 zero​width nbsp "
# Tab, carriage return, ANSI colour escape, bell, quotes, backslashes and printf directives.
_CONTROL = 'tab\there cr\rhere \x1b[31mred\x1b[0m bell\x07 "quoted" back\\slash %s %n %d {} '


def body_for(kind: str, seq: int, size: int) -> str:
    """Body text of roughly `size` UTF-8 bytes for the given kind."""
    if kind in ("plain", "long"):
        unit = _PLAIN
    elif kind == "multiline":
        unit = "\n".join(_TRACE) + "\n"
    elif kind == "unicode":
        unit = _UNICODE
    elif kind == "control":
        unit = _CONTROL
    else:
        raise ValueError(f"unknown kind {kind!r}")
    out: list[str] = []
    n = 0
    i = seq % len(unit)  # start the pattern at a different place per seq
    unit = unit[i:] + unit[:i]
    while n < size:
        out.append(unit)
        n += len(unit.encode())
    text = "".join(out)
    # trim to size bytes without splitting a code point
    return text.encode()[:size].decode(errors="ignore")


def build(run: str, src: str, seq: int, ts_host_ns: int, kind: str = "plain", size: int = 256) -> str:
    head = f"lc1 run={run} src={src} seq={seq} ts={ts_host_ns} kind={kind} |"
    text = head + body_for(kind, seq, max(0, size - len(head) - 14)) + "|"
    return f"{text} crc={zlib.crc32(text.encode()):08x}"


def parse_head(text: str) -> dict | None:
    m = HEAD_RE.search(text)
    if not m:
        return None
    return {
        "run": m["run"],
        "src": m["src"],
        "seq": int(m["seq"]),
        "ts": int(m["ts"]),
        "kind": m["kind"],
        "start": m.start(),
    }


def rsyslog_unescape(text: str) -> str:
    return RSYSLOG_ESC_RE.sub(lambda m: chr(int(m[1], 8)), text)


def check(text: str) -> str:
    """Classify a delivered message.

    exact        byte-for-byte what was written
    recoverable  differs only by rsyslog's control-character escaping, which can be reversed
    truncated    the CRC trailer is missing: the tail was cut
    damaged      the trailer is there but the content changed
    unparsed     no canary header found
    """
    head = parse_head(text)
    if head is None:
        return "unparsed"
    payload = text[head["start"] :].rstrip("\n")
    if _crc_ok(payload):
        return "exact"
    if CRC_RE.search(payload) is None:
        return "truncated"
    if _crc_ok(rsyslog_unescape(payload)):
        return "recoverable"
    return "damaged"


def _crc_ok(payload: str) -> bool:
    m = CRC_RE.search(payload)
    if not m:
        return False
    return zlib.crc32(payload[: m.start()].encode()) == int(m[1], 16)
