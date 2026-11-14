"""Canary writer. Runs on the host under test; standard library only.

Writes numbered canaries through the host's real logging paths and records each one in a
SQLite ledger (the ground truth):

  syslog    libc syslog(3) -> /dev/log -> rsyslog -> /var/log/syslog
  journald  native journal protocol -> /run/systemd/journal/socket -> /var/log/journal

The ledger stores the true wall clock, a monotonic clock and the host clock as the payload
carries it. They differ only when the clock-skew fault moves the host clock, which this
writer reads from the same offset file libfaketime gives the logging daemons.

    python3 -m logcanary.writer --run RUN --cond COND --rate 20 --count 1200 --ledger PATH
"""

from __future__ import annotations

import argparse
import hashlib
import json
import socket
import sqlite3
import struct
import sys
import syslog
import time

from logcanary.message import build

JOURNAL_SOCKET = "/run/systemd/journal/socket"
CLOCK_FILE = "/run/logcanary/faketime"


def journal_payload(fields: dict[str, str]) -> bytes:
    """Encode fields in the native journal protocol (see systemd's JOURNAL_NATIVE_PROTOCOL)."""
    out = bytearray()
    for k, v in fields.items():
        b = v.encode()
        if b"\n" in b:
            out += k.encode() + b"\n" + struct.pack("<Q", len(b)) + b + b"\n"
        else:
            out += k.encode() + b"=" + b + b"\n"
    return bytes(out)


class Journal:
    def __init__(self) -> None:
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        # libsystemd raises the send buffer to 8 MB too (journal-send.c).
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 8 * 1024 * 1024)

    def send(self, msg: str) -> str:
        data = journal_payload({"MESSAGE": msg, "SYSLOG_IDENTIFIER": "logcanary", "PRIORITY": "6"})
        try:
            self.sock.sendto(data, JOURNAL_SOCKET)
            return ""
        except OSError as e:
            return type(e).__name__


def send_syslog(msg: str) -> str:
    # syslog(3) returns nothing: a dropped message is invisible to the caller by design.
    syslog.syslog(syslog.LOG_INFO, msg)
    return ""


def read_offset_ns(path: str = CLOCK_FILE) -> int:
    try:
        with open(path) as f:
            return int(float(f.read().strip() or 0) * 1e9)
    except (OSError, ValueError):
        return 0


SCHEMA = """create table if not exists ledger (
  run text, cond text, src text, seq integer, ts_wall_ns integer, ts_mono_ns integer,
  ts_host_ns integer, size_bytes integer, kind text, sha1 text, send_err text,
  primary key (run, src, seq))"""


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    ap.add_argument("--cond", required=True)
    ap.add_argument("--rate", type=float, default=20.0, help="canaries per second per path, 0 = flat out")
    ap.add_argument("--count", type=int, default=1200)
    ap.add_argument("--size", type=int, default=256, help="message size in bytes")
    ap.add_argument("--sizes", default="", help="comma list of sizes, cycled by seq (overrides --size)")
    ap.add_argument("--kinds", default="plain", help="comma list, cycled by seq")
    ap.add_argument("--srcs", default="syslog,journald")
    ap.add_argument("--ledger", required=True)
    a = ap.parse_args(argv)

    kinds = a.kinds.split(",")
    sizes = [int(s) for s in a.sizes.split(",")] if a.sizes else [a.size]
    srcs = a.srcs.split(",")
    db = sqlite3.connect(a.ledger)
    db.execute(SCHEMA)
    syslog.openlog("logcanary", syslog.LOG_PID, syslog.LOG_USER)
    journal = Journal()
    senders = {"syslog": send_syslog, "journald": journal.send}

    rows: list[tuple] = []
    errors = 0
    offset_ns, offset_read = read_offset_ns(), time.monotonic()
    t0 = time.monotonic()
    for seq in range(a.count):
        if a.rate > 0:
            delay = t0 + seq / a.rate - time.monotonic()
            if delay > 0:
                time.sleep(delay)
        now_mono = time.monotonic()
        if now_mono - offset_read > 0.25:
            offset_ns, offset_read = read_offset_ns(), now_mono
        kind = kinds[seq % len(kinds)]
        size = sizes[seq % len(sizes)]
        for src in srcs:
            wall = time.time_ns()
            mono = time.monotonic_ns()
            msg = build(a.run, src, seq, wall + offset_ns, kind, size)
            err = senders[src](msg)
            errors += bool(err)
            rows.append((a.run, a.cond, src, seq, wall, mono, wall + offset_ns, len(msg.encode()), kind,
                         hashlib.sha1(msg.encode()).hexdigest(), err))
        if len(rows) >= 5000:
            db.executemany("insert into ledger values (?,?,?,?,?,?,?,?,?,?,?)", rows)
            db.commit()
            rows.clear()
    elapsed = time.monotonic() - t0
    db.executemany("insert into ledger values (?,?,?,?,?,?,?,?,?,?,?)", rows)
    db.commit()
    db.close()
    json.dump({"run": a.run, "count": a.count, "srcs": srcs, "elapsed_s": round(elapsed, 3),
               "achieved_rate": round(a.count / elapsed, 1) if elapsed else None, "send_errors": errors},
              sys.stdout)
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
