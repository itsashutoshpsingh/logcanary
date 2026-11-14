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
    return f"{x:.0f}%" if x >= 10 or x == 0 else f"{x:.1f}%"


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
    silent_pct = 100 * len(silent) / len(lossy) if lossy else 0.0

    metrics = [
        {"label": "canaries written and reconciled", "value": f"{sent:,}"},
        {"label": f"worst default loss ({SHIP[worst['shipper']]}, {ALL[worst['condition']].title.lower()})",
         "value": pct(f(worst["loss_mean_pct"]))},
        {"label": "lossy streams with no log line about the loss", "value": f"{len(silent)} of {len(lossy)}"},
    ]
    b = cm.get(("burst_4k", "filebeat", "journald"))
    if b:
        metrics.append({"label": "20,000-event burst dropped by journald before any shipper",
                        "value": pct(100 * f(b["lost_before_disk_total"]) / f(b["sent_total"]))})
    r = cm.get(("shipper_restart", "fluentbit", "syslog"))
    if r:
        metrics.append({"label": "fluent bit default, lost across a graceful restart",
                        "value": pct(f(r["loss_mean_pct"]))})
    r = cm.get(("baseline", "filebeat", "syslog"))
    if r:
        metrics.append({"label": "filebeat default median delay at 20 events/s",
                        "value": f"{f(r['lat_p50_ms']) / 1000:.1f} s"})
    trunc = [r for r in default if r["condition"] == "sizes" and r["src"] == "syslog"]
    if trunc:
        metrics.append({"label": "64 KB messages via rsyslog that arrived intact",
                        "value": pct(_intact_at("sizes", "syslog", 65536))})
    if tuned:
        tw = max(tuned, key=lambda r: f(r["loss_mean_pct"]))
        metrics.append({"label": f"worst loss with tuned shippers ({SHIP[tw['shipper']]}, "
                                 f"{ALL[tw['condition']].title.split(' (')[0].lower()})",
                        "value": pct(f(tw["loss_mean_pct"]))})
    metrics.append({"label": "runs (each read by three shippers on two log paths)", "value": str(n_runs)})

    headline = (f"{sent:,} numbered canaries written through rsyslog and journald on an Ubuntu 24.04 host and "
                f"counted again in Elasticsearch across {n_cond} conditions: default pipelines lost up to "
                f"{pct(f(worst['loss_mean_pct']))} ({SHIP[worst['shipper']]}, "
                f"{ALL[worst['condition']].title.lower()}), and {len(silent)} of {len(lossy)} lossy streams left no "
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
            "viz": viz(cm)}


def _intact_at(cond: str, src: str, size: int) -> float:
    """Share of canaries of one nominal size that arrived intact via Filebeat on a path."""
    from logcanary.figures import _checks_by

    c = _checks_by(cond, "size").get(("filebeat", src), {}).get(size, {})
    n = sum(c.values())
    return 100 * c.get("intact", 0) / n if n else 0.0


def viz(cm: dict) -> list[dict]:
    def tone(v: float) -> str:
        return "good" if v == 0 else ("warn" if v < 5 else "bad")

    out = []
    for c, title in (("es_down_120", "Elasticsearch down for 2 minutes: share of canaries lost (file path)"),
                     ("shipper_restart", "A graceful shipper restart: share of canaries lost (file path)")):
        bars = [{"label": SHIP[s], "value": round(f(cm[(c, s, "syslog")]["loss_mean_pct"]), 2),
                 "tone": tone(f(cm[(c, s, "syslog")]["loss_mean_pct"]))} for s in SHIP if (c, s, "syslog") in cm]
        if bars:
            out.append({"title": title, "unit": "%", "bars": bars})
    bars = []
    for c, lbl in (("baseline", "20/s"), ("burst_1k", "1,000/s"), ("burst_4k", "4,000/s"), ("burst_max", "max")):
        r = cm.get((c, "filebeat", "journald"))
        if r:
            v = round(100 * f(r["lost_before_disk_total"]) / f(r["sent_total"]), 2)
            bars.append({"label": lbl, "value": v, "tone": tone(v)})
    if bars:
        out.append({"title": "journald dropped canaries before any shipper saw them as the rate rose", "unit": "%",
                    "bars": bars})
    return out[:3]


def main() -> None:
    s = build()
    (RESULTS / "summary.json").write_text(json.dumps(s, indent=2, ensure_ascii=False) + "\n")
    print(s["headline"])
