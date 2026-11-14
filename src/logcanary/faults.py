"""Fault actions. Each one is a function of the lab; a condition schedules them at offsets (in
seconds) from the moment the writer starts. Every action is logged with its true start and end
time so charts and the reconciler can line events up against it."""

from __future__ import annotations

import threading
import time

from logcanary import lab


def _each_shipper(fn) -> None:
    ts = [threading.Thread(target=fn, args=(c,)) for c in lab.SHIPPERS.values()]
    for t in ts:
        t.start()
    for t in ts:
        t.join()


def shipper_restart(**_) -> None:
    """Graceful restart: SIGTERM, up to 10 s to finish, then start."""
    _each_shipper(lambda c: lab.sh("docker", "restart", "-t", "10", c))


def shipper_kill(**_) -> None:
    """Crash: SIGKILL, no chance to flush or save state."""
    _each_shipper(lambda c: lab.sh("docker", "kill", "-s", "KILL", c))


def shipper_start(**_) -> None:
    _each_shipper(lambda c: lab.sh("docker", "start", c))


def partition(**_) -> None:
    """Cut the shippers off the lab network (the host keeps writing to disk)."""
    _each_shipper(lambda c: lab.sh("docker", "network", "disconnect", lab.NETWORK, c))


def heal(**_) -> None:
    _each_shipper(lambda c: lab.sh("docker", "network", "connect", lab.NETWORK, c))


def es_stop(**_) -> None:
    lab.sh("docker", "stop", "-t", "30", lab.ES)


def es_start(**_) -> None:
    lab.sh("docker", "start", lab.ES)
    lab.es_up()


def es_freeze(**_) -> None:
    """Elasticsearch stops answering but keeps its sockets open (docker pause)."""
    lab.sh("docker", "pause", lab.ES)


def es_thaw(**_) -> None:
    lab.sh("docker", "unpause", lab.ES)


def clock(offset_s: int = 0, **_) -> None:
    """Move the host clock as journald, rsyslog and the writer's payload see it."""
    lab.dexec(lab.HOST, "sh", "-c", f"echo {offset_s:+d} > /run/logcanary/faketime")


def daemon_kill(name: str = "rsyslog", **_) -> None:
    """SIGKILL a host logging daemon; the host's supervisor restarts it within about a second,
    as systemd's Restart= would."""
    lab.dexec(lab.HOST, "/usr/local/bin/lc-daemon", "kill", name)


def logrotate(conf: str = "stock", **_) -> None:
    lab.dexec(lab.HOST, "logrotate", "-f", "-s", "/var/lib/logcanary/logrotate.state",
              f"/etc/logcanary/logrotate/{conf}.conf")


def journal_rotate(**_) -> None:
    """Ask journald to rotate its files (SIGUSR2, what `journalctl --rotate` requests)."""
    lab.dexec(lab.HOST, "sh", "-c", "kill -USR2 $(cat /run/logcanary/journald.pid)")


def journal_vacuum(size: str = "1M", **_) -> None:
    lab.dexec(lab.HOST, "journalctl", "-D", "/var/log/journal", f"--vacuum-size={size}")


def journald_limits(max_use: str = "", max_file: str = "", **_) -> None:
    """Set (or with no arguments clear) journald size limits, then restart journald to apply."""
    if max_use:
        conf = f"[Journal]\\nSystemMaxUse={max_use}\\nSystemMaxFileSize={max_file or max_use}\\n"
        lab.dexec(lab.HOST, "sh", "-c", f"mkdir -p /etc/systemd/journald.conf.d && printf '{conf}' "
                  "> /etc/systemd/journald.conf.d/lc.conf")
    else:
        lab.dexec(lab.HOST, "rm", "-f", "/etc/systemd/journald.conf.d/lc.conf")
    daemon_kill(name="journald")
    time.sleep(3)


ACTIONS = {f.__name__: f for f in (
    shipper_restart, shipper_kill, shipper_start, partition, heal, es_stop, es_start, es_freeze, es_thaw,
    clock, daemon_kill, logrotate, journal_rotate, journal_vacuum, journald_limits)}


def run_schedule(schedule: list[tuple[float, str, dict]], t0: float, log: list[dict]) -> None:
    """Run (offset_s, action, kwargs) items in order, each at t0 + offset (time.monotonic)."""
    for offset, name, kwargs in sorted(schedule, key=lambda x: x[0]):
        delay = t0 + offset - time.monotonic()
        if delay > 0:
            time.sleep(delay)
        start = lab.now_ns()
        err = ""
        try:
            ACTIONS[name](**kwargs)
        except Exception as e:  # keep going: a failed fault is recorded, not fatal
            err = repr(e)[:300]
        log.append({"action": name, "kwargs": kwargs, "offset_s": offset, "start_ns": start,
                    "end_ns": lab.now_ns(), "error": err})
