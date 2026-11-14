"""Run one repeat of one condition and write its raw results to results/runs/<cond>/<run>/."""

from __future__ import annotations

import csv
import gzip
import io
import json
import shutil
import subprocess
import threading
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

from logcanary import alerts, faults, lab, metrics, reconcile_es
from logcanary.conditions import Condition

RESULTS = lab.ROOT / "results"
RUNS = RESULTS / "runs"
LEDGER_COLS = ["src", "seq", "ts_wall_ns", "ts_host_ns", "size_bytes", "kind", "send_err"]
ARRIVAL_COLS = ["shipper", "src", "seq", "kind", "check", "ts_event_ns", "ingested_ns", "shipper_ns",
                "fields_ok", "msg_len"]


def log(msg: str) -> None:
    print(f"{datetime.now(UTC):%H:%M:%S} {msg}", flush=True)


def write_csv_gz(path: Path, cols: list[str], rows: list[dict]) -> None:
    with gzip.open(path, "wt", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def read_csv_gz(path: Path) -> list[dict]:
    with gzip.open(path, "rt", newline="") as f:
        return list(csv.DictReader(f))


def shipper_counters() -> dict:
    return {
        "filebeat": alerts.filebeat_counters(lab.http_get("http://127.0.0.1:5066/stats")),
        "fluentbit": alerts.fluentbit_counters(lab.http_get("http://127.0.0.1:2020/api/v1/metrics")),
        "vector": alerts.vector_counters(lab.http_get("http://127.0.0.1:9598/metrics")),
    }


def current_shipper_set() -> str | None:
    r = lab.sh("docker", "inspect", "-f", "{{range .Mounts}}{{.Source}} {{end}}", lab.SHIPPERS["vector"],
               check=False)
    for s in ("tuned", "default"):
        if f"/shippers/{s}/" in r.stdout:
            return s
    return None


def reset_host_logs() -> None:
    """Empty the syslog file and the journal so freshly created shippers (which read existing
    files from the beginning) do not re-ship every earlier run."""
    lab.dexec(lab.HOST, "sh", "-c",
              "rm -f /var/log/syslog.* && : > /var/log/syslog && "
              "kill -USR2 $(cat /run/logcanary/journald.pid) && sleep 1 && "
              "journalctl -D /var/log/journal --vacuum-time=1s >/dev/null 2>&1; true")


def use_shipper_set(name: str) -> None:
    if current_shipper_set() == name and all(lab.running(c) for c in lab.SHIPPERS.values()):
        return
    log(f"switching shippers to the {name!r} set")
    lab.compose("rm", "-sf", "filebeat", "fluentbit", "vector")
    lab.sh("docker", "volume", "rm", "-f", "logcanary_fbstate", check=False)
    reset_host_logs()
    lab.compose("up", "-d", "filebeat", "fluentbit", "vector", env={"SHIPPER_SET": name})
    time.sleep(15)


def preflight(cond: Condition) -> dict:
    notes = {"restarted": []}
    if not lab.running(lab.ES):
        lab.sh("docker", "start", lab.ES)
        notes["restarted"].append(lab.ES)
    lab.es_up()
    use_shipper_set(cond.shipper_set)
    for c in (lab.HOST, *lab.SHIPPERS.values()):
        st = lab.state(c)
        if st.get("Paused"):
            lab.sh("docker", "unpause", c)
        if not st.get("Running"):
            notes["restarted"].append(c)
            notes.setdefault("found_dead", {})[c] = {"oom": st.get("OOMKilled"), "exit": st.get("ExitCode")}
            lab.sh("docker", "start", c)
    for c in lab.SHIPPERS.values():  # make sure every shipper is on the network (a failed heal)
        nets = lab.sh("docker", "inspect", "-f", "{{json .NetworkSettings.Networks}}", c).stdout
        if lab.NETWORK not in nets:
            lab.sh("docker", "network", "connect", lab.NETWORK, c)
            notes["restarted"].append(c + ":network")
    lab.dexec(lab.HOST, "sh", "-c", "echo +0 > /run/logcanary/faketime")
    if not cond.setup and "lc.conf" in lab.dexec(lab.HOST, "ls", "/etc/systemd/journald.conf.d", check=False):
        faults.journald_limits()  # left over from an interrupted run
        notes["restarted"].append("journald:limits-cleared")
    if notes["restarted"]:
        time.sleep(15)
    return notes


def settle(client, run: str, expected: int, min_quiet_s: int, incomplete_quiet_s: int = 90,
           max_wait_s: int = 1500) -> dict:
    """Wait until no shipper's count for this run has changed for a while: min_quiet_s once every
    shipper holds at least `expected` documents, incomplete_quiet_s (longer than Filebeat's 60 s
    maximum retry backoff) while any shipper is short. Anything later still is caught by the
    final re-reconcile (`logcanary reconcile`)."""
    t0 = time.monotonic()
    last, last_change = None, time.monotonic()
    trail = []
    while True:
        try:
            c = reconcile_es.counts(client, run)
        except Exception:
            c = None
        now = time.monotonic()
        trail.append({"t_s": round(now - t0, 1), "counts": c})
        if c is not None and c != last:
            last, last_change = c, now
        complete = c is not None and min(c.values()) >= expected
        if c is not None and now - last_change >= (min_quiet_s if complete else incomplete_quiet_s):
            break
        if now - t0 > max_wait_s:
            break
        time.sleep(5)
    return {"waited_s": round(time.monotonic() - t0, 1), "final_counts": last, "trail": trail}


def run_once(cond: Condition, repeat: int) -> Path:
    run = uuid.uuid4().hex[:12]
    out = RUNS / cond.name / f"r{repeat}-{run}"
    out.mkdir(parents=True, exist_ok=True)
    log(f"{cond.name} repeat {repeat} run {run}")
    notes = preflight(cond)
    client = lab.es()
    for action, kw in cond.setup:
        faults.ACTIONS[action](**kw)
    mark = json.loads(lab.host_py("-m", "logcanary.hostprobe", "mark"))
    before = shipper_counters()
    t_start = lab.now_ns()
    ledger_path = f"/var/lib/logcanary/{run}.db"
    cmd = ["docker", "exec", *lab.PYENV, lab.HOST, "python3", "-m", "logcanary.writer", "--run", run,
           "--cond", cond.name, "--rate", str(cond.rate), "--count", str(cond.count), "--size", str(cond.size),
           "--kinds", cond.kinds, "--ledger", ledger_path]
    if cond.sizes:
        cmd += ["--sizes", cond.sizes]
    fault_log: list[dict] = []
    writer = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    t0 = time.monotonic()
    ft = threading.Thread(target=faults.run_schedule, args=(list(cond.faults), t0, fault_log))
    ft.start()
    w_out, w_err = writer.communicate()
    t_writer_done = lab.now_ns()
    ft.join()
    writer_summary = json.loads(w_out.strip().splitlines()[-1]) if w_out.strip() else {"stderr": w_err[-2000:]}
    log(f"  writer done {writer_summary.get('elapsed_s')} s, faults done; settling")
    st = settle(client, run, 2 * cond.count, cond.settle_s)
    arrivals = reconcile_es.fetch(client, run)
    probe = json.loads(lab.host_py("-m", "logcanary.hostprobe", "collect", run, json.dumps(mark)))
    after = shipper_counters()
    since = datetime.fromtimestamp(t_start / 1e9, UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    comp = {}
    for name, c in lab.SHIPPERS.items():
        r = lab.sh("docker", "logs", "--since", since, c, check=False)
        lines = (r.stdout + r.stderr).splitlines()
        comp[name] = alerts.classify_lines(name, lines)
        (out / f"{name}.log.gz").write_bytes(gzip.compress("\n".join(lines).encode()))
    for name in ("rsyslog", "journald", "supervisor"):
        comp[name] = alerts.classify_lines(name, probe[name])
    ledger_csv = lab.host_py("-m", "logcanary.hostprobe", "ledger", ledger_path)
    lab.dexec(lab.HOST, "rm", "-f", ledger_path)
    ledger = list(csv.DictReader(io.StringIO(ledger_csv)))
    for action, kw in cond.teardown:
        faults.ACTIONS[action](**kw)

    write_csv_gz(out / "ledger.csv.gz", LEDGER_COLS, ledger)
    write_csv_gz(out / "arrivals.csv.gz", ARRIVAL_COLS, arrivals)
    states = {c: {k: lab.state(c).get(k) for k in ("Running", "OOMKilled", "RestartCount", "StartedAt")}
              for c in (lab.ES, lab.HOST, *lab.SHIPPERS.values())}
    meta = {
        "run": run, "condition": cond.name, "title": cond.title, "repeat": repeat,
        "params": {k: getattr(cond, k) for k in ("rate", "count", "size", "sizes", "kinds", "shipper_set",
                                                 "settle_s")},
        "faults": fault_log, "t_start_ns": t_start, "t_writer_done_ns": t_writer_done,
        "writer": writer_summary, "settle": st, "preflight": notes, "probe_on_disk": probe["on_disk"],
        "host_supervisor": probe["supervisor"], "journald_stderr_tail": probe["journald_stderr_tail"],
        "counters_before": before, "counters_after": after, "mem_mb": lab.mem_usage_mb(), "states": states,
    }
    (out / "meta.json").write_text(json.dumps(meta, indent=1))
    (out / "alerts.json").write_text(json.dumps(comp, indent=1))
    result = summarise(out)
    log("  " + "  ".join(f"{k}: loss {v['loss_pct']}% dup {v['duplicates']}" for k, v in result.items()))
    return out


def _ledger_rows(rows: list[dict], src: str) -> list[dict]:
    return [{"seq": int(r["seq"]), "ts_wall_ns": int(r["ts_wall_ns"]), "ts_host_ns": int(r["ts_host_ns"]),
             "kind": r["kind"], "send_err": r["send_err"]} for r in rows if r["src"] == src]


def _arrival_rows(rows: list[dict], shipper: str, src: str) -> list[dict]:
    out = []
    for r in rows:
        if r["shipper"] != shipper or r["src"] != src:
            continue
        out.append({"seq": int(r["seq"]), "check": r["check"],
                    "ts_event_ns": int(r["ts_event_ns"]) if r["ts_event_ns"] else None,
                    "ingested_ns": int(r["ingested_ns"]), "fields_ok": r["fields_ok"] in ("True", True)})
    return out


def summarise(out: Path) -> dict:
    """(Re)compute result.json for a run directory from its raw files."""
    meta = json.loads((out / "meta.json").read_text())
    comp = json.loads((out / "alerts.json").read_text())
    ledger = read_csv_gz(out / "ledger.csv.gz")
    arrivals = read_csv_gz(out / "arrivals.csv.gz")
    result = {}
    for shipper in lab.SHIPPERS:
        d = alerts.delta(meta["counters_before"].get(shipper, {}), meta["counters_after"].get(shipper, {}))
        for src in lab.SRCS:
            m = metrics.compute(_ledger_rows(ledger, src), _arrival_rows(arrivals, shipper, src),
                                on_disk=meta["probe_on_disk"].get(src))
            host_daemon = "rsyslog" if src == "syslog" else "journald"
            m["alert_shipper"] = comp[shipper]["status"]
            m["alert_host"] = comp[host_daemon]["status"]
            m["shipper_counted_loss"] = alerts.counted_loss(shipper, d)
            m["silent"] = bool(m["lost"]) and "loss" not in (comp[shipper]["status"], comp[host_daemon]["status"])
            result[f"{shipper}/{src}"] = m
    (out / "result.json").write_text(json.dumps(result, indent=1))
    return {k: v for k, v in result.items()}


def done_repeats(cond: Condition) -> int:
    d = RUNS / cond.name
    return len([p for p in d.glob("r*") if (p / "result.json").exists()]) if d.exists() else 0


def run_condition(cond: Condition, repeats: int | None = None) -> None:
    want = repeats or cond.repeats
    for d in (RUNS / cond.name).glob("r*") if (RUNS / cond.name).exists() else []:
        if not (d / "result.json").exists():  # an interrupted run: discard it
            shutil.rmtree(d)
    for rep in range(done_repeats(cond) + 1, want + 1):
        try:
            run_once(cond, rep)
        except Exception:  # record and move on; the next preflight repairs the lab
            import traceback

            log(f"  run failed: {traceback.format_exc()[-1500:]}")
            for action, kw in cond.teardown:
                try:
                    faults.ACTIONS[action](**kw)
                except Exception:
                    pass
