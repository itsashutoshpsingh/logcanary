"""results/summary.json for the portfolio. Every value is read from results/conditions.csv and
results/runs.csv, which `logcanary report` builds from the raw run files."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from logcanary.conditions import ALL

ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "results"
SHIP = {"filebeat": "Filebeat", "fluentbit": "Fluent Bit", "vector": "Vector"}
PATH = {"syslog": "rsyslog file", "journald": "journald"}


def _rows(name: str) -> list[dict]:
    with open(RESULTS / name) as f:
        return list(csv.DictReader(f))


def f(x) -> float:
    return float(x) if x not in (None, "", "None") else 0.0


def pct(x: float) -> str:
    """Same rounding as results/table.md, so every summary number can be found there."""
    from logcanary.report import fmt_pct

    return fmt_pct(x) + "%"


def build() -> dict:
    cond = _rows("conditions.csv")
    runs = _rows("runs.csv")
    cm = {(r["condition"], r["shipper"], r["src"]): r for r in cond}
    default = [r for r in cond if r["group"] != "tuned"]
    tuned = [r for r in cond if r["group"] == "tuned"]

    # canaries written = ledger rows; each run's ledger is the same for all three shippers
    sent = sum(int(r["sent"]) for r in runs if r["shipper"] == "filebeat")
    n_runs = len({r["run"] for r in runs})
    n_cond = len({r["condition"] for r in runs})
    worst = max(default, key=lambda r: f(r["loss_mean_pct"]))
    lossy = [r for r in runs if int(r["lost"]) > 0]
    silent = [r for r in lossy if r["silent"] == "True"]

    def m(label: str, cond: str, shipper: str, src: str, key: str = "loss_mean_pct") -> None:
        r = cm.get((cond, shipper, src))
        if r:
            metrics.append({"label": label, "value": pct(f(r[key]))})

    metrics = [
        {"label": f"Worst default loss ({SHIP[worst['shipper']]}, {ALL[worst['condition']].title})",
         "value": pct(f(worst["loss_mean_pct"]))},
        {"label": "Lossy streams with no log line about the loss", "value": f"{len(silent)} of {len(lossy)}"},
    ]
    if tuned:
        tw = max(tuned, key=lambda r: f(r["loss_mean_pct"]))
        metrics.append({"label": f"Worst loss with tuned shippers ({SHIP[tw['shipper']]}, "
                                 f"{ALL[tw['condition']].title.split(' (')[0]})",
                        "value": pct(f(tw["loss_mean_pct"]))})
    m("Fluent Bit default config, lost across a graceful restart", "shipper_restart", "fluentbit", "syslog")
    m("Lost on the file path when rsyslog was killed and restarted within 1 s", "daemon_crash", "filebeat", "syslog")
    m("Vector, journal path, 50,000 canaries as fast as the writer can", "burst_max", "vector", "journald")
    if any(r["condition"] == "sizes" and r["src"] == "syslog" for r in default):
        metrics.append({"label": "64 KB messages via rsyslog that arrived intact",
                        "value": pct(_intact_at("sizes", "syslog", 65536))})
    r = cm.get(("baseline", "filebeat", "syslog"))
    if r:
        metrics.append({"label": "Filebeat default median delay at 20 events/s",
                        "value": f"{f(r['lat_p50_ms']) / 1000:.1f} s"})
    metrics.append({"label": "Canaries written and reconciled", "value": f"{sent:,}"})
    metrics.append({"label": "Runs (each read by three shippers on two log paths)", "value": str(n_runs)})

    headline = (f"{sent:,} numbered canaries written through rsyslog and journald on an Ubuntu 24.04 host and "
                f"counted again in Elasticsearch across {n_cond} conditions: default pipelines lost up to "
                f"{pct(f(worst['loss_mean_pct']))} ({SHIP[worst['shipper']]}, "
                f"{ALL[worst['condition']].title}), and {len(silent)} of {len(lossy)} lossy streams left no "
                "log line anywhere saying events were lost.")

    charts = [
        ("loss_by_condition.png", "Loss by condition", "Mean percentage of canaries lost per condition, shipper "
         "and log path, with 95% confidence intervals"),
        ("timelines.png", "Fault timelines", "Cumulative share of canaries indexed over time for nine conditions, "
         "with fault windows shaded"),
        ("alerts.png", "Who reported loss", "For each lossy condition, shipper and path, the share of runs where the "
         "shipper log, host daemon log or shipper counters reported lost events"),
        ("bursts.png", "Burst loss", "Loss under bursts split into canaries the host never wrote to disk and "
         "canaries missing in Elasticsearch"),
        ("latency_baseline_ecdf.png", "Delay at steady load", "Cumulative distribution of ingest latency at 20 "
         "events per second for each shipper and path"),
        ("latency_p95_heatmap.png", "Delay under faults", "95th percentile ingest latency per condition, shipper "
         "and path"),
        ("fidelity.png", "Field fidelity", "Share of canaries arriving with every field intact by message size "
         "and by content type"),
        ("clock_skew.png", "Clock jumps", "Difference between the SIEM event time and the true write time during "
         "host clock jumps of +2 hours and -10 minutes"),
        ("rule_blind_spots.png", "Rule blind spots", "Share of sent canaries a 5 minute scheduled rule never sees, "
         "split into lost and arrived too late"),
        ("duplicates.png", "Duplicates", "Duplicate documents as a share of sent canaries per condition"),
        ("default_vs_tuned.png", "Default against tuned", "Loss with default and tuned shipper settings for five "
         "fault conditions"),
        ("pipeline.png", "Lab pipeline", "Architecture: canary writer and ledger on the host, rsyslog and journald, "
         "three shippers, Elasticsearch and the reconciler"),
    ]
    charts = [{"path": f"docs/img/{p}", "label": lbl, "alt": alt} for p, lbl, alt in charts
              if (ROOT / "docs" / "img" / p).exists()]
    return {"project": "logcanary", "headline": headline, "metrics": metrics[:10], "charts": charts,
            "viz": viz(cm, lossy, silent)}


def _intact_at(cond: str, src: str, size: int) -> float:
    """Share of canaries of one nominal size that arrived intact via Filebeat on a path."""
    from logcanary.figures import _checks_by

    c = _checks_by(cond, "size").get(("filebeat", src), {}).get(size, {})
    n = sum(c.values())
    return 100 * c.get("intact", 0) / n if n else 0.0


def viz(cm: dict, lossy: list[dict], silent: list[dict]) -> list[dict]:
    def tone(v: float) -> str:
        return "good" if v == 0 else ("warn" if v < 5 else "bad")

    def bar(label: str, key: tuple) -> dict | None:
        r = cm.get(key)
        if r is None:
            return None
        v = round(f(r["loss_mean_pct"]), 3)
        return {"label": label, "value": v, "tone": tone(v)}

    out = []
    bars = [bar(SHIP[s], ("es_down_120", s, "syslog")) for s in SHIP]
    if all(bars):
        out.append({"title": "Elasticsearch down for 2 minutes: share of canaries lost on the file path",
                    "unit": "%", "bars": bars})
    bars = [b for c, lbl in (("shipper_restart", "Restart"), ("shipper_crash", "Crash"), ("partition_60", "Partition"))
            for b in (bar(f"{lbl}, default", (c, "fluentbit", "syslog")),
                      bar(f"{lbl}, tuned", (c + "_tuned", "fluentbit", "syslog")))]
    if all(bars):
        out.append({"title": "Fluent Bit on the file path: share of canaries lost with default and tuned settings",
                    "unit": "%", "bars": bars})
    said = [("Shipper log said so", sum(r["alert_shipper"] == "loss" for r in lossy)),
            ("Host daemon log said so", sum(r["alert_host"] == "loss" for r in lossy)),
            ("No log line anywhere", len(silent))]
    out.append({"title": f"Of {len(lossy)} lossy streams, which ones left a log line about the loss", "unit": "count",
                "bars": [{"label": lbl, "value": n, "tone": "bad" if lbl.startswith("No") else "neutral"}
                         for lbl, n in said]})
    return out[:3]


def main() -> None:
    s = build()
    (RESULTS / "summary.json").write_text(json.dumps(s, indent=2, ensure_ascii=False) + "\n")
    print(s["headline"])
