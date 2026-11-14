"""Host-side probe. Runs on the host under test; standard library only.

    python3 -m logcanary.hostprobe mark
        prints where the syslog file and the journal stand now
    python3 -m logcanary.hostprobe collect RUN MARK_JSON
        counts canaries of RUN that reached disk on each path, and returns what rsyslog, journald
        and the supervisor said about themselves since the mark
    python3 -m logcanary.hostprobe ledger PATH
        prints the SQLite ledger as CSV
"""

from __future__ import annotations

import csv
import glob
import gzip
import json
import os
import re
import sqlite3
import subprocess
import sys

SYSLOG = "/var/log/syslog"
JOURNAL_DIR = "/var/log/journal"
SUPERVISOR_LOG = "/var/lib/logcanary/supervisor.log"


def journal_cursor() -> str | None:
    r = subprocess.run(["journalctl", "-D", JOURNAL_DIR, "-n", "1", "-o", "json"],
                       capture_output=True, text=True)
    lines = r.stdout.strip().splitlines()
    return json.loads(lines[-1]).get("__CURSOR") if lines else None


def mark() -> dict:
    st = os.stat(SYSLOG)
    sup = 0
    if os.path.exists(SUPERVISOR_LOG):
        with open(SUPERVISOR_LOG) as f:
            sup = sum(1 for _ in f)
    return {"syslog_inode": st.st_ino, "syslog_size": st.st_size, "journal_cursor": journal_cursor(),
            "supervisor_lines": sup}


def _syslog_files() -> list[str]:
    files = [SYSLOG] + sorted(glob.glob(SYSLOG + ".*"))
    return [f for f in files if os.path.isfile(f)]


def _read(path: str) -> str:
    opener = gzip.open if path.endswith(".gz") else open
    with opener(path, "rt", errors="replace") as f:
        return f.read()


def syslog_seqs(run: str) -> set[int]:
    pat = re.compile(rf"run={run} src=syslog seq=(\d+) ")
    out: set[int] = set()
    for f in _syslog_files():
        out.update(int(m) for m in pat.findall(_read(f)))
    return out


def journal_seqs(run: str, cursor: str | None) -> set[int]:
    cmd = ["journalctl", "-D", JOURNAL_DIR, "-o", "cat", "SYSLOG_IDENTIFIER=logcanary"]
    if cursor:
        cmd.insert(3, f"--after-cursor={cursor}")
    r = subprocess.run(cmd, capture_output=True, text=True, errors="replace")
    pat = re.compile(rf"run={run} src=journald seq=(\d+) ")
    return {int(m) for m in pat.findall(r.stdout)}


def rsyslog_lines(m: dict) -> list[str]:
    """rsyslog's own messages (it logs to itself) written since the mark."""
    st = os.stat(SYSLOG)
    texts = []
    if st.st_ino == m["syslog_inode"]:
        with open(SYSLOG, "rb") as f:
            f.seek(m["syslog_size"])
            texts.append(f.read().decode(errors="replace"))
    else:  # rotated since the mark: the old file is the newest rotated one
        for f in _syslog_files()[:3]:
            texts.append(_read(f))
    return [ln for t in texts for ln in t.splitlines() if " rsyslogd" in ln and "logcanary[" not in ln]


def journald_lines(cursor: str | None) -> list[str]:
    cmd = ["journalctl", "-D", JOURNAL_DIR, "-o", "cat", "SYSLOG_IDENTIFIER=systemd-journald"]
    if cursor:
        cmd.insert(3, f"--after-cursor={cursor}")
    r = subprocess.run(cmd, capture_output=True, text=True, errors="replace")
    return r.stdout.splitlines()


def collect(run: str, m: dict) -> dict:
    sup = []
    if os.path.exists(SUPERVISOR_LOG):
        with open(SUPERVISOR_LOG) as f:
            sup = f.read().splitlines()[m["supervisor_lines"]:]
    with open("/var/lib/logcanary/journald.stderr", errors="replace") as f:
        jstderr = f.read().splitlines()[-20:]
    return {
        "on_disk": {"syslog": len(syslog_seqs(run)), "journald": len(journal_seqs(run, m["journal_cursor"]))},
        "rsyslog": rsyslog_lines(m),
        "journald": journald_lines(m["journal_cursor"]),
        "journald_stderr_tail": jstderr,
        "supervisor": sup,
    }


def dump_ledger(path: str) -> None:
    db = sqlite3.connect(path)
    w = csv.writer(sys.stdout)
    cols = ["src", "seq", "ts_wall_ns", "ts_mono_ns", "ts_host_ns", "size_bytes", "kind", "send_err"]
    w.writerow(cols)
    for row in db.execute(f"select {','.join(cols)} from ledger order by src, seq"):
        w.writerow(row)


def main(argv: list[str]) -> int:
    if argv[0] == "mark":
        print(json.dumps(mark()))
    elif argv[0] == "collect":
        print(json.dumps(collect(argv[1], json.loads(argv[2]))))
    elif argv[0] == "ledger":
        dump_ledger(argv[1])
    else:
        print(__doc__, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
