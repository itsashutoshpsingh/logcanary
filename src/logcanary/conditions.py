"""The experiment matrix. Rates are canaries per second on each of the two log paths; every
canary is written once to syslog and once to journald, so the host sees twice the rate."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Condition:
    name: str
    title: str
    rate: float = 20.0
    count: int = 1800
    size: int = 256
    sizes: str = ""
    kinds: str = "plain"
    faults: tuple = ()  # (offset_s, action, kwargs)
    setup: tuple = ()  # (action, kwargs) before the writer starts
    teardown: tuple = ()  # (action, kwargs) after arrivals settle
    repeats: int = 5
    shipper_set: str = "default"
    settle_s: int = 20
    group: str = "fault"
    extra: dict = field(default_factory=dict)


def _c(name, title, **kw) -> Condition:
    return Condition(name=name, title=title, **kw)


SIZES = "1024,4096,8000,8200,16384,32768,65536"

MATRIX: list[Condition] = [
    _c("baseline", "Steady 20/s for 90 s", group="load"),
    _c("burst_1k", "Burst: 10,000 at 1,000/s", rate=1000, count=10000, group="load"),
    _c("burst_4k", "Burst: 20,000 in 5 s (4,000/s)", rate=4000, count=20000, group="load"),
    _c("burst_max", "Burst: 50,000 as fast as the writer can", rate=0, count=50000, repeats=3, group="load"),
    _c("shipper_restart", "Shipper restart (SIGTERM) at 30 s", rate=50, count=4000,
       faults=((30, "shipper_restart", {}),)),
    _c("shipper_crash", "Shipper crash (SIGKILL) at 30 s, back at 40 s", rate=50, count=4000,
       faults=((30, "shipper_kill", {}), (40, "shipper_start", {}))),
    _c("partition_60", "Network partition 60 s", rate=50, count=6000,
       faults=((20, "partition", {}), (80, "heal", {}))),
    _c("partition_300", "Network partition 300 s", rate=50, count=18000, repeats=3,
       faults=((20, "partition", {}), (320, "heal", {}))),
    _c("es_down_120", "Elasticsearch stopped for 120 s", rate=50, count=9000, repeats=3,
       faults=((20, "es_stop", {}), (140, "es_start", {}))),
    _c("es_down_600", "Elasticsearch stopped for 10 min", rate=20, count=14400, repeats=2,
       faults=((30, "es_stop", {}), (630, "es_start", {}))),
    _c("es_freeze_120", "Elasticsearch frozen (paused) for 120 s", rate=50, count=9000, repeats=3,
       faults=((20, "es_freeze", {}), (140, "es_thaw", {}))),
    _c("sizes", "Message sizes 1 KB to 64 KB", rate=20, count=700, sizes=SIZES, repeats=3, group="fidelity"),
    _c("mangling", "Multiline, unicode and control characters", rate=20, count=1200,
       kinds="plain,multiline,unicode,control", repeats=3, group="fidelity"),
    _c("clock_fwd_2h", "Host clock +2 h from 30 s to 90 s", rate=20, count=2400, repeats=3, group="clock",
       faults=((30, "clock", {"offset_s": 7200}), (90, "clock", {"offset_s": 0}))),
    _c("clock_back_10m", "Host clock -10 min from 30 s to 90 s", rate=20, count=2400, repeats=3, group="clock",
       faults=((30, "clock", {"offset_s": -600}), (90, "clock", {"offset_s": 0}))),
    _c("rotate_stock", "Log rotation (Ubuntu stock logrotate) and journal rotation", rate=50, count=4000,
       repeats=3, faults=((30, "logrotate", {"conf": "stock"}), (30, "journal_rotate", {}))),
    _c("rotate_copytruncate", "Log rotation with copytruncate", rate=50, count=4000, repeats=3,
       faults=((30, "logrotate", {"conf": "copytruncate"}),)),
    _c("journal_vacuum", "Journal rotate and vacuum to 1 MB mid-stream", rate=50, count=4000, repeats=3,
       faults=((30, "journal_rotate", {}), (31, "journal_vacuum", {"size": "1M"}))),
    _c("daemon_crash", "rsyslog and journald SIGKILL at 30 s (restarted within 1 s)", rate=50, count=4000,
       faults=((30, "daemon_kill", {"name": "rsyslog"}), (30, "daemon_kill", {"name": "journald"}))),
    _c("disk_pressure", "Partition 150 s with aggressive rotation and an 8 MB journal cap",
       rate=200, count=40000, size=2048, repeats=3,
       setup=(("journald_limits", {"max_use": "8M", "max_file": "2M"}),),
       faults=((20, "partition", {}), (50, "logrotate", {"conf": "nodelay"}),
               (80, "logrotate", {"conf": "nodelay"}), (110, "logrotate", {"conf": "nodelay"}),
               (140, "logrotate", {"conf": "nodelay"}), (170, "heal", {})),
       teardown=(("journald_limits", {}),)),
]

TUNED = [
    Condition(**{**c.__dict__, "name": c.name + "_tuned", "title": c.title + " (tuned shippers)",
                 "shipper_set": "tuned", "repeats": 3, "group": "tuned"})
    for c in MATRIX
    if c.name in ("shipper_restart", "shipper_crash", "partition_60", "es_down_120", "disk_pressure")
]

ALL = {c.name: c for c in MATRIX + TUNED}
