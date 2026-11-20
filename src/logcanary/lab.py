"""Thin helpers around the Docker lab (lab/docker-compose.yml) and the Elasticsearch client."""

from __future__ import annotations

import json
import os
import subprocess
import time
import urllib.request
from pathlib import Path

from elasticsearch import Elasticsearch

ROOT = Path(__file__).resolve().parents[2]
LAB = ROOT / "lab"
ES_URL = os.environ.get("LC_ES_URL", "http://127.0.0.1:9200")
NETWORK = "lcnet"
HOST = "lc-host"
ES = "lc-es"
SHIPPERS = {"filebeat": "lc-filebeat", "fluentbit": "lc-fluentbit", "vector": "lc-vector"}
SRCS = ("syslog", "journald")
PYENV = ["-e", "PYTHONPATH=/opt/logcanary/src"]


def sh(*cmd: str, check: bool = True, timeout: float | None = 600) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=check, capture_output=True, text=True, timeout=timeout)


def dexec(container: str, *cmd: str, check: bool = True, timeout: float | None = 600) -> str:
    return sh("docker", "exec", *PYENV, container, *cmd, check=check, timeout=timeout).stdout


def host_py(*args: str, timeout: float | None = 900) -> str:
    return dexec(HOST, "python3", *args, timeout=timeout)


def compose(*args: str, env: dict | None = None) -> subprocess.CompletedProcess:
    e = dict(os.environ, **(env or {}))
    return subprocess.run(["docker", "compose", "-f", str(LAB / "docker-compose.yml"), *args],
                          check=True, capture_output=True, text=True, env=e)


def es() -> Elasticsearch:
    return Elasticsearch(ES_URL, request_timeout=60)


def es_up(timeout: float = 240) -> float:
    """Wait for the cluster to answer with yellow or green. Returns seconds waited."""
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        try:
            with urllib.request.urlopen(ES_URL + "/_cluster/health", timeout=3) as r:
                if json.load(r)["status"] in ("yellow", "green"):
                    return time.monotonic() - t0
        except OSError:
            pass
        time.sleep(1)
    raise TimeoutError("Elasticsearch did not come up")


def install_es_assets() -> None:
    c = es()
    c.ingest.put_pipeline(id="lc-ingest", body=json.loads((LAB / "es/pipeline.json").read_text()))
    t = json.loads((LAB / "es/template.json").read_text())
    c.indices.put_index_template(name="lc", body=t)
    # On a nearly full disk Elasticsearch holds merges back (default: 95% used) and then throttles
    # indexing; that confounded part of the matrix (docs/what-went-wrong.md), so the lab allows
    # merges until 500 MB are left.
    c.cluster.put_settings(persistent={"indices.merge.disk.watermark.high": "500mb"})


def running(container: str) -> bool:
    r = sh("docker", "inspect", "-f", "{{.State.Running}}", container, check=False)
    return r.stdout.strip() == "true"


def state(container: str) -> dict:
    r = sh("docker", "inspect", "-f", "{{json .State}}", container, check=False)
    return json.loads(r.stdout) if r.returncode == 0 else {}


def http_get(url: str, timeout: float = 5) -> str | None:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return r.read().decode()
    except OSError:
        return None


def mem_usage_mb() -> dict[str, float]:
    r = sh("docker", "stats", "--no-stream", "--format", "{{.Name}} {{.MemUsage}}", check=False)
    out = {}
    for line in r.stdout.splitlines():
        name, usage = line.split(" ", 1)
        if not name.startswith("lc-"):
            continue
        v = usage.split("/")[0].strip()
        num = float("".join(ch for ch in v if ch.isdigit() or ch == "."))
        out[name] = round(num * {"GiB": 1024, "MiB": 1, "KiB": 1 / 1024}.get(v.lstrip("0123456789."), 1), 1)
    return out


def now_ns() -> int:
    return time.time_ns()
