"""Aggregate run results into tables.

  results/runs.csv         one row per run x shipper x log path
  results/conditions.csv   one row per condition x shipper x log path, across repeats
  results/table.md         the same as Markdown, plus the headline loss table

`logcanary report --check` recomputes each run's result from its raw files (where present) and
every table and summary.json from the results, and fails if anything committed no longer follows.
"""

from __future__ import annotations

import csv
import gzip
import io
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

from logcanary import metrics
from logcanary.conditions import ALL, JAMMY, MATRIX, TUNED

RESULTS = Path(__file__).resolve().parents[2] / "results"
RUNS = RESULTS / "runs"
SHIPPERS = ("filebeat", "fluentbit", "vector")
SRCS = ("syslog", "journald")
NAMES = {"filebeat": "Filebeat 8.19.25", "fluentbit": "Fluent Bit 5.1.5", "vector": "Vector 0.61.0",
         "syslog": "rsyslog file", "journald": "journald"}
ORDER = [c.name for c in MATRIX + TUNED + JAMMY]
RUN_COLS = ["condition", "group", "repeat", "run", "shipper", "src", "sent", "arrived", "docs", "lost", "loss_pct",
            "duplicates", "dup_pct", "lat_p50_ms", "lat_p95_ms", "lat_p99_ms", "lat_max_ms", "intact_pct",
            "exact_pct", "recoverable_pct", "truncated", "damaged", "skew_p50_ms", "skew_max_abs_ms",
            "late_5m_pct", "missed_rule_pct_of_arrived", "blind_pct", "send_errors", "on_disk",
            "lost_before_disk", "gap_rule_fires", "alert_shipper", "alert_host", "shipper_counted_loss",
            "shipper_crashes", "silent",
            "late_after_settle", "es_throttled"]
ES_EVENTS = RESULTS / "es_events.jsonl.gz"


def run_dirs() -> list[Path]:
    return sorted(p for p in RUNS.glob("*/r*") if (p / "result.json").exists())


def has_raw(d: Path) -> bool:
    """The ledger and arrivals are kept out of git (hashes in results/raw_sha256.txt); a clone has
    only each run's compact files, from which every table and summary.json still follow."""
    return (d / "ledger.csv.gz").exists() and (d / "arrivals.csv.gz").exists()


def _ns(ts: str) -> int:
    from logcanary.reconcile_es import ts_ns

    return ts_ns(ts)


def throttle_windows(events: list[dict]) -> list[tuple[int, int]]:
    """Spans (ns) when Elasticsearch throttled indexing on at least one shard because merges were
    held back. A shard's throttle ends at "stop throttling indexing" or when the node stops; a node
    that died without logging "stopping" (killed with the machine) is taken to have stopped at its
    last logged line before the next "started"."""
    out, n, start, last = [], 0, None, None
    for e in sorted(events, key=lambda e: e["@timestamp"]):
        t, msg = _ns(e["@timestamp"]), e["message"]
        node = e["log.logger"].endswith("node.Node")
        if msg.startswith("now throttling indexing"):
            n += 1
            start = t if n == 1 else start
        elif n and msg.startswith("stop throttling indexing"):
            n -= 1
            if n == 0:
                out.append((start, t))
        elif n and node and msg.startswith(("stopping", "started")):
            out.append((start, t if msg.startswith("stopping") else last))
            n = 0
        last = t
    if n:
        out.append((start, None))  # still throttled when the log ends
    return out


def _es_windows() -> list[tuple[int, int | None]]:
    if not ES_EVENTS.exists():
        return []
    with gzip.open(ES_EVENTS, "rt") as f:
        return throttle_windows([json.loads(x) for x in f])


def es_throttled(meta: dict, windows: list) -> bool:
    """Did the run, from writer start to the end of settling, overlap a throttling window?"""
    a = meta["t_start_ns"]
    b = meta["t_writer_done_ns"] + int(meta["settle"]["waited_s"] * 1e9)
    return any(s < b and (e is None or e > a) for s, e in windows)


def run_rows() -> list[dict]:
    rows = []
    windows = _es_windows()
    for d in run_dirs():
        cond = d.parent.name
        if cond not in ALL:
            continue
        rep, run = d.name[1:].split("-", 1)
        res = json.loads((d / "result.json").read_text())
        settle_p = d / "result_settle.json"
        at_settle = json.loads(settle_p.read_text()) if settle_p.exists() else None
        throttled = es_throttled(json.loads((d / "meta.json").read_text()), windows)
        for key, m in res.items():
            shipper, src = key.split("/")
            row = {"condition": cond, "group": ALL[cond].group, "repeat": int(rep), "run": run,
                   "shipper": shipper, "src": src, **{k: m.get(k) for k in RUN_COLS if k in m}}
            row["late_after_settle"] = (m["arrived"] - at_settle[key]["arrived"]) if at_settle else 0
            row["es_throttled"] = throttled
            rows.append(row)
    rows.sort(key=lambda r: (ORDER.index(r["condition"]), r["repeat"], SHIPPERS.index(r["shipper"]),
                             SRCS.index(r["src"])))
    return rows


def _f(x) -> float | None:
    return None if x in (None, "") else float(x)


def aggregate(rows: list[dict]) -> list[dict]:
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for r in rows:
        groups[(r["condition"], r["shipper"], r["src"])].append(r)
    out = []
    for (cond, shipper, src), rs in groups.items():
        loss = [_f(r["loss_pct"]) for r in rs]
        m, lo, hi = metrics.mean_ci(loss)
        dup = [_f(r["dup_pct"]) for r in rs]
        skews = [_f(r["skew_max_abs_ms"]) for r in rs if r["skew_max_abs_ms"] is not None]

        def med(k, rs=rs):
            v = [_f(r[k]) for r in rs if r[k] is not None]
            return round(metrics.percentile(v, 50), 1) if v else None

        def mean(k, rs=rs):
            v = [_f(r[k]) for r in rs if r[k] is not None]
            return round(sum(v) / len(v), 3) if v else None

        alerts_s = Counter(r["alert_shipper"] for r in rs)
        alerts_h = Counter(r["alert_host"] for r in rs)
        out.append({
            "condition": cond, "title": ALL[cond].title, "group": ALL[cond].group, "shipper": shipper, "src": src,
            "repeats": len(rs), "sent_total": sum(int(r["sent"]) for r in rs),
            "lost_total": sum(int(r["lost"]) for r in rs),
            "loss_mean_pct": _r(m), "loss_ci_lo": _r(lo), "loss_ci_hi": _r(hi),
            "loss_min_pct": _r(min(loss)), "loss_max_pct": _r(max(loss)),
            "runs_with_loss": sum(1 for x in loss if x and x > 0),
            "dup_mean_pct": _r(sum(dup) / len(dup)), "dup_total": sum(int(r["duplicates"]) for r in rs),
            "lat_p50_ms": med("lat_p50_ms"), "lat_p95_ms": med("lat_p95_ms"), "lat_max_ms": max(
                (_f(r["lat_max_ms"]) for r in rs if r["lat_max_ms"] is not None), default=None),
            "intact_mean_pct": mean("intact_pct"), "exact_mean_pct": mean("exact_pct"),
            "recoverable_mean_pct": mean("recoverable_pct"),
            "truncated_total": sum(int(r["truncated"]) for r in rs),
            "skew_max_abs_ms": max(skews, key=abs) if skews else None,
            "blind_mean_pct": mean("blind_pct"), "lost_before_disk_total": sum(
                int(r["lost_before_disk"] or 0) for r in rs),
            "silent_runs": sum(1 for r in rs if r["silent"] in (True, "True")),
            "gap_rule_runs": sum(1 for r in rs if r["gap_rule_fires"] in (True, "True")),
            "shipper_counted_loss_total": sum(_f(r["shipper_counted_loss"]) or 0 for r in rs),
            "late_after_settle_total": sum(int(r["late_after_settle"] or 0) for r in rs),
            "es_throttled_runs": sum(1 for r in rs if r["es_throttled"] in (True, "True")),
            "alert_shipper": "/".join(f"{k}:{v}" for k, v in sorted(alerts_s.items())),
            "alert_host": "/".join(f"{k}:{v}" for k, v in sorted(alerts_h.items())),
        })
    out.sort(key=lambda r: (ORDER.index(r["condition"]), SHIPPERS.index(r["shipper"]), SRCS.index(r["src"])))
    return out


def _r(x, nd=3):
    return None if x is None else round(x, nd)


def to_csv(rows: list[dict], cols: list[str] | None = None) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=cols or list(rows[0]), extrasaction="ignore", lineterminator="\n")
    w.writeheader()
    w.writerows(rows)
    return buf.getvalue()


def fmt_pct(x) -> str:
    if x is None:
        return "n/a"
    x = float(x)
    return "0" if x == 0 else (f"{x:.2f}" if x < 10 else f"{x:.1f}")


def fmt_ms(x) -> str:
    if x is None:
        return "n/a"
    x = float(x)
    return f"{x / 1000:.1f} s" if abs(x) >= 1000 else f"{x:.0f} ms"


def headline_table(agg: list[dict]) -> str:
    by = {(a["condition"], a["shipper"], a["src"]): a for a in agg}
    conds = [c for c in ORDER if any(k[0] == c for k in by)]
    head = ("| Condition | n | " + " | ".join(f"{NAMES[s].split()[0] if s != 'fluentbit' else 'Fluent Bit'} "
                                            f"file / journal" for s in SHIPPERS)
            + " | Silent streams | Runs during ES throttling |")
    lines = [head, "|" + "---|" * (len(SHIPPERS) + 4)]
    for c in conds:
        cells = []
        silent = 0
        runs = 0
        for s in SHIPPERS:
            a, b = by.get((c, s, "syslog")), by.get((c, s, "journald"))
            cells.append(f"{fmt_pct(a and a['loss_mean_pct'])} / {fmt_pct(b and b['loss_mean_pct'])}")
            for x in (a, b):
                if x:
                    silent += x["silent_runs"]
                    runs += x["repeats"]
        n = max(by[(c, s, src)]["repeats"] for s in SHIPPERS for src in SRCS if (c, s, src) in by)
        thr = by.get((c, "filebeat", "syslog"), {}).get("es_throttled_runs", 0)
        lines.append(f"| {ALL[c].title} | {n} | " + " | ".join(cells) + f" | {silent} of {runs} | {thr} of {n} |")
    return "\n".join(lines)


def full_table(agg: list[dict]) -> str:
    lines = ["| Condition | Shipper | Path | n | Sent | Loss % mean (95% CI) | worst | Dup % | p50 | p95 | "
             "Intact % | Max skew | Blind to 5 min rule % | Lost before disk | Silent | ES throttled |",
             "|" + "---|" * 16]
    for a in agg:
        ci = (f" ({fmt_pct(max(0.0, a['loss_ci_lo']))} to {fmt_pct(a['loss_ci_hi'])})"
              if a["loss_ci_lo"] is not None and a["loss_mean_pct"] else "")
        lines.append(
            f"| {a['condition']} | {NAMES[a['shipper']]} | {NAMES[a['src']]} | {a['repeats']} | {a['sent_total']} | "
            f"{fmt_pct(a['loss_mean_pct'])}{ci} | {fmt_pct(a['loss_max_pct'])} | {fmt_pct(a['dup_mean_pct'])} | "
            f"{fmt_ms(a['lat_p50_ms'])} | {fmt_ms(a['lat_p95_ms'])} | {fmt_pct(a['intact_mean_pct'])} | "
            f"{fmt_ms(a['skew_max_abs_ms'])} | {fmt_pct(a['blind_mean_pct'])} | {a['lost_before_disk_total']} | "
            f"{a['silent_runs']} of {a['repeats']} | {a['es_throttled_runs']} of {a['repeats']} |")
    return "\n".join(lines)


def build() -> dict[str, str]:
    rows = run_rows()
    agg = aggregate(rows)
    md = ("# Results\n\nGenerated by `logcanary report` from `results/runs/*/*/result.json`. "
          "Loss is the share of canaries written on the host that never reached Elasticsearch, after settling "
          "and a final re-reconcile. Definitions: `docs/method.md`.\n\n"
          "## Loss %, mean over repeats (rsyslog file path / journald path)\n\n"
          "A silent stream is one run, shipper and path that lost canaries with no log line about it. "
          "\"Runs during ES throttling\": runs that overlapped a window in which Elasticsearch throttled "
          "indexing because low disk space held merges back (`results/es_events.jsonl.gz`).\n\n"
          + headline_table(agg) +
          "\n\n## Every metric\n\n" + full_table(agg) + "\n")
    return {"runs.csv": to_csv(rows, RUN_COLS), "conditions.csv": to_csv(agg), "table.md": md}


def recompute_runs() -> list[str]:
    """Recompute each run's result.json from its raw files; return the runs that differ."""
    from logcanary.runner import compute_result

    bad = []
    for d in filter(has_raw, run_dirs()):
        new = json.loads(json.dumps(compute_result(d)))
        if new != json.loads((d / "result.json").read_text()):
            bad.append(str(d))
    return bad


def finalize_run(client, d: Path) -> int:
    """Second, final reconcile of one run: keep the at-settle result, re-query Elasticsearch,
    recompute. Returns the number of documents found."""
    from logcanary import reconcile_es, runner

    (d / "result_settle.json").write_text((d / "result.json").read_text())
    run = d.name.split("-", 1)[1]
    arrivals = reconcile_es.fetch(client, run)
    runner.write_csv_gz(d / "arrivals.csv.gz", runner.ARRIVAL_COLS, arrivals)
    runner.summarise(d)
    return len(arrivals)


def finalize_old(min_age_s: int = 900, prune: bool = True, force: bool = False) -> None:
    """Finalize every condition whose runs are all done and whose last run ended at least
    min_age_s ago, then delete its documents from Elasticsearch to keep the lab's disk small.
    Runs already finalized (result_settle.json present) are never queried again, because their
    documents may be gone."""
    import time

    from logcanary import lab, runner

    client = lab.es()
    for cond in ALL.values():
        dirs = [d for d in run_dirs() if d.parent.name == cond.name]
        todo = [d for d in dirs if not (d / "result_settle.json").exists()]
        if not todo or (len(dirs) < cond.repeats and not force):
            continue
        last = max(json.loads((d / "meta.json").read_text())["t_writer_done_ns"] for d in dirs)
        if time.time_ns() - last < min_age_s * 1e9:
            continue
        for d in todo:
            n = finalize_run(client, d)
            runner.log(f"finalized {cond.name}/{d.name}: {n} docs")
        if prune:
            runs = [d.name.split("-", 1)[1] for d in todo]
            q = {"bool": {"should": [{"match_phrase": {"message": f"run={r}"}} for r in runs],
                          "minimum_should_match": 1}}
            client.delete_by_query(index="lc-*", query=q, conflicts="proceed", refresh=True,
                                   wait_for_completion=True, request_timeout=3600)
            client.indices.forcemerge(index="lc-*", only_expunge_deletes=True, request_timeout=3600)


def reconcile_all() -> None:
    """Finalize every run not finalized yet, whatever its age (end of the matrix)."""
    finalize_old(min_age_s=0, prune=False, force=True)


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[2:] if argv is None else argv
    check = "--check" in argv
    files = build()
    if check:
        bad = recompute_runs()
        for name, text in files.items():
            if (RESULTS / name).read_text() != text:
                bad.append(f"results/{name}")
        from logcanary.summary import build as build_summary

        if json.loads((RESULTS / "summary.json").read_text()) != json.loads(json.dumps(build_summary())):
            bad.append("results/summary.json")
        if bad:
            print("out of date:\n  " + "\n  ".join(bad))
            return 1
        n_raw = sum(map(has_raw, run_dirs()))
        print(f"ok: {len(files)} tables and summary.json follow from {len(run_dirs())} runs' result files; "
              f"{n_raw} of them recomputed from raw files")
        return 0
    from logcanary.runner import summarise

    for d in filter(has_raw, run_dirs()):  # result.json is rebuilt from the raw files where present
        summarise(d)
    files = build()
    for name, text in files.items():
        (RESULTS / name).write_text(text)
    print(f"wrote {', '.join(files)} from {len(run_dirs())} runs")
    return 0
