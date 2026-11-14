"""Did anything in the pipeline say it lost data?

Reads what each component wrote about itself during a run (shipper stderr, rsyslog's and
journald's own messages, the supervisor log) and the counters the shippers expose, and
classifies each component as:

  loss   at least one line says events were dropped, discarded, suppressed or not retried
  warn   warnings or errors, none of them about lost events (e.g. "connection refused")
  quiet  nothing at warning level or above
"""

from __future__ import annotations

import json
import re

LOSS_RE = re.compile(
    r"drop|discard|lost|suppress|cannot be retried|not be retried|retries exhausted|retry limit|"
    r"rejected|overflow|truncat|too large|exceed|out of memory|oom",
    re.I,
)
LEVEL_RE = {
    "filebeat": re.compile(r'"log\.level":"(warn|error|fatal)"'),
    "fluentbit": re.compile(r"\[\s*(warn|error)\]"),
    "vector": re.compile(r"\s(WARN|ERROR)\s"),
}


def classify_lines(component: str, lines: list[str]) -> dict:
    """Host daemons (rsyslog, journald, supervisor) have no levels: every line they write about
    themselves during a run counts as a warning."""
    lvl = LEVEL_RE.get(component)
    warn = [ln for ln in lines if (lvl.search(ln) if lvl else ln.strip())]
    loss = [ln for ln in warn if LOSS_RE.search(ln)]
    status = "loss" if loss else ("warn" if warn else "quiet")
    return {"status": status, "warn_lines": len(warn), "loss_lines": len(loss),
            "samples": [ln[:300] for ln in (loss or warn)[:5]]}


def filebeat_counters(stats_json: str | None) -> dict:
    if not stats_json:
        return {}
    s = json.loads(stats_json)
    lb = s.get("libbeat", {})
    out = lb.get("output", {}).get("events", {})
    pipe = lb.get("pipeline", {}).get("events", {})
    return {"acked": out.get("acked"), "failed": out.get("failed"), "dropped": out.get("dropped"),
            "pipeline_dropped": pipe.get("dropped"), "pipeline_failed": pipe.get("failed"),
            "pipeline_retry": pipe.get("retry")}


def fluentbit_counters(metrics_json: str | None) -> dict:
    if not metrics_json:
        return {}
    m = json.loads(metrics_json).get("output", {})
    es = next((v for k, v in m.items() if k.startswith("es")), {})
    return {"proc_records": es.get("proc_records"), "dropped_records": es.get("dropped_records"),
            "retried_records": es.get("retried_records"), "retries_failed": es.get("retries_failed"),
            "errors": es.get("errors")}


_PROM_RE = re.compile(r'^(\w+)\{([^}]*)\}\s+([0-9.eE+-]+)', re.M)


def vector_counters(prom_text: str | None) -> dict:
    if not prom_text:
        return {}
    out = {"discarded": 0.0, "errors": 0.0, "buffer_discarded": 0.0, "sent_events": 0.0}
    for name, labels, value in _PROM_RE.findall(prom_text):
        if 'component_id="es"' not in labels:
            continue
        v = float(value)
        if name == "vector_component_discarded_events_total":
            out["discarded"] += v
        elif name == "vector_component_errors_total":
            out["errors"] += v
        elif name == "vector_buffer_discarded_events_total":
            out["buffer_discarded"] += v
        elif name == "vector_component_sent_events_total":
            out["sent_events"] += v
    return out


def delta(before: dict, after: dict) -> dict:
    """Counter change over a run. A counter that went down means the process restarted, so the
    value after is the change since that restart."""
    out = {}
    for k, v in after.items():
        if not isinstance(v, int | float):
            continue
        b = before.get(k)
        out[k] = v - b if isinstance(b, int | float) and v >= b else v
    return out


def counted_loss(shipper: str, d: dict) -> float:
    """Events the shipper itself counted as given up on, from its counter deltas."""
    if shipper == "filebeat":
        return (d.get("dropped") or 0) + (d.get("pipeline_dropped") or 0)
    if shipper == "fluentbit":
        return d.get("dropped_records") or 0  # retries_failed counts chunks, not records
    if shipper == "vector":
        return (d.get("discarded") or 0) + (d.get("buffer_discarded") or 0)
    return 0
