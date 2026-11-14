"""Pull every canary of a run out of Elasticsearch and turn each document into an arrival row.

Uses the scroll helper, never a plain search: a plain search stops at 10,000 hits and a
reconciler that stops early invents loss.
"""

from __future__ import annotations

import tomllib
from datetime import datetime
from pathlib import Path

from elasticsearch import Elasticsearch, helpers

from logcanary.message import check, parse_head

FIDELITY = tomllib.loads((Path(__file__).parent / "fidelity.toml").read_text())
INDEX_TO_SHIPPER = {"lc-filebeat": "filebeat", "lc-fluentbit": "fluentbit", "lc-vector": "vector"}


def ts_ns(value) -> int | None:
    """Parse an Elasticsearch date (ISO 8601, up to nanoseconds) to integer ns since the epoch."""
    if value is None:
        return None
    if isinstance(value, int | float):
        return int(value * 1_000_000)
    s = str(value)
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    frac_ns = 0
    if "." in s:
        head, rest = s.split(".", 1)
        i = 0
        while i < len(rest) and rest[i].isdigit():
            i += 1
        frac, tz = rest[:i], rest[i:]
        frac_ns = int((frac + "000000000")[:9])
        s = head + tz
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    return int(dt.timestamp()) * 1_000_000_000 + frac_ns


def get_path(doc: dict, dotted: str):
    if dotted in doc:
        return doc[dotted]
    cur = doc
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def to_arrival(shipper: str, doc: dict, run: str) -> dict | None:
    msg = doc.get("message")
    if not isinstance(msg, str):
        return None
    head = parse_head(msg)
    if head is None or head["run"] != run:
        return None
    src = head["src"]
    expected = FIDELITY.get(shipper, {}).get(src, {})
    fields_ok = all(get_path(doc, k) == v for k, v in expected.items())
    ts_event = ts_ns(doc.get("@timestamp"))
    return {
        "shipper": shipper,
        "src": src,
        "seq": head["seq"],
        "kind": head["kind"],
        "check": check(msg),
        "ts_event_ns": ts_event,
        "ingested_ns": ts_ns(get_path(doc, "event.ingested")),
        "shipper_ns": ts_ns(doc.get("lc_shipper_ts")),
        "fields_ok": fields_ok and ts_event is not None,
        "msg_len": len(msg.encode()),
    }


def fetch(client: Elasticsearch, run: str) -> list[dict]:
    q = {"query": {"match_phrase": {"message": f"run={run}"}}}
    out = []
    for hit in helpers.scan(client, index="lc-*", query=q, size=5000, scroll="5m"):
        shipper = INDEX_TO_SHIPPER.get(hit["_index"])
        if shipper is None:
            continue
        a = to_arrival(shipper, hit["_source"], run)
        if a is not None:
            out.append(a)
    return out


def counts(client: Elasticsearch, run: str) -> dict[str, int]:
    """Document count per shipper for a run (cheap, used to decide when arrivals have settled)."""
    client.indices.refresh(index="lc-*", ignore_unavailable=True)
    r = client.search(index="lc-*", size=0, query={"match_phrase": {"message": f"run={run}"}},
                      aggs={"by": {"terms": {"field": "_index", "size": 10}}})
    got = {INDEX_TO_SHIPPER.get(b["key"], b["key"]): b["doc_count"] for b in r["aggregations"]["by"]["buckets"]}
    return {s: got.get(s, 0) for s in INDEX_TO_SHIPPER.values()}
