"""Pure metrics: ledger rows and arrival rows in, numbers out. No I/O, no lab needed.

Ledger row:  {"seq": int, "ts_wall_ns": int, "ts_host_ns": int, "kind": str, "send_err": str}
Arrival row: {"seq": int, "check": str, "ts_event_ns": int|None, "ingested_ns": int, "fields_ok": bool}

Definitions are in docs/method.md.
"""

from __future__ import annotations

import math
from collections import Counter

NS_PER_MS = 1_000_000
RULE_INTERVAL_NS = 5 * 60 * 10**9  # Elastic Security rule default: runs every 5 minutes
RULE_LOOKBACK_NS = 6 * 60 * 10**9  # and searches now-6m (5 m interval + 1 m additional look-back)
LATE_NS = 5 * 60 * 10**9  # the guide's simpler cut: ingest latency over 5 minutes


def percentile(values: list[float], q: float) -> float | None:
    """Linear-interpolated percentile, q in [0, 100]. None for an empty list."""
    if not values:
        return None
    s = sorted(values)
    k = (len(s) - 1) * q / 100
    lo, hi = math.floor(k), math.ceil(k)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def rule_seen_probability(ts_event_ns: int, ingested_ns: int,
                          interval_ns: int = RULE_INTERVAL_NS, lookback_ns: int = RULE_LOOKBACK_NS) -> float:
    """Chance that a scheduled rule sees this event, over a uniformly random rule phase.

    The rule runs at times T = phase + k * interval and searches @timestamp in [T - lookback, T].
    The event is searchable from `ingested`. So some run must fall in [a, b] with
    a = max(ingested, ts_event) and b = ts_event + lookback. If that window is at least one
    interval long a run always lands in it; if it is empty none can.
    """
    a = max(ingested_ns, ts_event_ns)
    b = ts_event_ns + lookback_ns
    return min(1.0, max(0.0, (b - a) / interval_ns))


def ranges(seqs: list[int]) -> list[tuple[int, int]]:
    """Collapse sorted integers into inclusive ranges."""
    out: list[tuple[int, int]] = []
    for s in sorted(seqs):
        if out and s == out[-1][1] + 1:
            out[-1] = (out[-1][0], s)
        else:
            out.append((s, s))
    return out


def gap_rule(arrived: set[int]) -> dict:
    """What a SIEM-only sequence-gap rule could see, with no ledger: holes between the lowest and
    highest sequence number that arrived. It cannot see loss before the first or after the last."""
    if not arrived:
        return {"gap_rule_fires": False, "gap_rule_missing": 0}
    lo, hi = min(arrived), max(arrived)
    missing = (hi - lo + 1) - len(arrived)
    return {"gap_rule_fires": missing > 0, "gap_rule_missing": missing}


def compute(ledger: list[dict], arrivals: list[dict], on_disk: int | None = None) -> dict:
    sent = {r["seq"]: r for r in ledger}
    n_sent = len(sent)
    first: dict[int, dict] = {}
    unknown = 0
    for a in arrivals:
        seq = a["seq"]
        if seq not in sent:
            unknown += 1
            continue
        if seq not in first or a["ingested_ns"] < first[seq]["ingested_ns"]:
            first[seq] = a
    n_arr = len(first)
    docs = len(arrivals) - unknown
    missing = sorted(set(sent) - set(first))

    lat, skew, p_seen = [], [], []
    checks = Counter()
    fields_ok = 0
    late = 0
    for seq, a in first.items():
        true_ns = sent[seq]["ts_wall_ns"]
        lat_ns = a["ingested_ns"] - true_ns
        lat.append(lat_ns / NS_PER_MS)
        late += lat_ns > LATE_NS
        checks[a["check"]] += 1
        fields_ok += bool(a["fields_ok"]) and a["check"] == "exact"
        if a.get("ts_event_ns") is not None:
            skew.append((a["ts_event_ns"] - true_ns) / NS_PER_MS)
            p_seen.append(rule_seen_probability(a["ts_event_ns"], a["ingested_ns"]))
        else:
            p_seen.append(0.0)  # no usable event time: a time-range rule cannot match it

    def pct(x: float, n: int) -> float | None:
        return round(100 * x / n, 3) if n else None

    seen = sum(p_seen)
    max_abs_skew = max(skew, key=abs) if skew else None
    out = {
        "sent": n_sent,
        "arrived": n_arr,
        "docs": docs,
        "lost": len(missing),
        "loss_pct": pct(len(missing), n_sent),
        "duplicates": docs - n_arr,
        "dup_pct": pct(docs - n_arr, n_sent),
        "lat_p50_ms": _r(percentile(lat, 50)),
        "lat_p95_ms": _r(percentile(lat, 95)),
        "lat_p99_ms": _r(percentile(lat, 99)),
        "lat_max_ms": _r(max(lat) if lat else None),
        "intact_pct": pct(fields_ok, n_arr),
        "exact_pct": pct(checks["exact"], n_arr),
        "recoverable_pct": pct(checks["recoverable"], n_arr),
        "truncated": checks["truncated"],
        "damaged": checks["damaged"] + checks["unparsed"],
        "skew_p50_ms": _r(percentile(skew, 50)),
        "skew_max_abs_ms": _r(max_abs_skew),
        "late_5m_pct": pct(late, n_arr),
        "missed_rule_pct_of_arrived": pct(n_arr - seen, n_arr),
        "blind_pct": pct(n_sent - seen, n_sent),
        "send_errors": sum(1 for r in ledger if r.get("send_err")),
        "missing_ranges": ranges(missing)[:20],
        "unknown_seq_docs": unknown,
        "on_disk": on_disk,
        "lost_before_disk": (n_sent - on_disk) if on_disk is not None else None,
    }
    out.update(gap_rule(set(first)))
    return out


def _r(x: float | None, nd: int = 1) -> float | None:
    return None if x is None else round(x, nd)


# Two-sided 95% Student t critical values by degrees of freedom.
T95 = {1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571, 6: 2.447, 7: 2.365, 8: 2.306, 9: 2.262,
       10: 2.228, 11: 2.201, 12: 2.179, 14: 2.145, 19: 2.093, 29: 2.045}


def mean_ci(values: list[float]) -> tuple[float | None, float | None, float | None]:
    """Mean and a 95% t confidence interval across repeats. With one value the interval is None."""
    v = [x for x in values if x is not None]
    if not v:
        return None, None, None
    m = sum(v) / len(v)
    if len(v) < 2:
        return m, None, None
    sd = math.sqrt(sum((x - m) ** 2 for x in v) / (len(v) - 1))
    df = len(v) - 1
    t = T95.get(df) or T95[max(k for k in T95 if k <= df)]
    h = t * sd / math.sqrt(len(v))
    return m, m - h, m + h
