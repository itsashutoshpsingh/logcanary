# What this does not show

**One lab is one lab.** Every number here is "this configuration, on this machine, lost X%". It is
not "Filebeat loses X%" or "journald loses X%". Change the rate, the message size, the disk, the
CPU share or a single setting and the numbers move. The point of the repository is the method and
the kinds of failure it exposes, with numbers that are true for this lab.

**Containers, not VMs.** The host under test is an Ubuntu 24.04 container, not a booted machine:

- No systemd PID 1. journald and rsyslog are started and restarted by a small supervisor that
  mimics systemd's restart behaviour. A real host's unit settings (`RateLimitIntervalSec` per
  unit, `LogRateLimitBurst=`, cgroup accounting) are not in play: every process in the container
  is in one cgroup, so journald's per-service rate limit applies to the whole container.
- The kernel is shared with the build machine. Nothing here moves the real clock, reboots a
  kernel, fills a real disk or drops packets with iptables. The clock fault moves only the
  user-space clock of journald, rsyslog and the canary payload (libfaketime); kernel timestamps
  such as journald's `_SOURCE_REALTIME_TIMESTAMP` stay true. On a real host they would move too,
  so Vector's journald path, which uses that field, would also be skewed there. Under the +2 h
  fake clock journald itself kept exiting ("Failed to run event loop: Invalid argument") and lost
  about half the journal-path canaries; that may be libfaketime, not journald, and only a VM with
  a real clock change can tell (`docs/what-went-wrong.md`, item 14).
- **No reboot test (guide C9).** Rebooting the host container also kills the writer and does not
  drop the page cache, so it would not test what a reboot tests. Daemon SIGKILL (`daemon_crash`)
  is the closest condition here.
- The shippers run in their own containers with the host's `/var/log` mounted read-only. They
  see the same files a host-installed agent sees, but a partition is `docker network disconnect`,
  which removes the interface. A real network failure (dropped packets, half-open TCP) can behave
  differently; `es_freeze_120` (Elasticsearch paused with sockets open) is the closer analogue.

**Not covered by this build:**

- **auditd.** The guide's second source. It needs the kernel audit subsystem, which a container
  cannot own without affecting the host; not attempted.
- **Second Linux distribution, Windows host, Splunk.** The guide's full-build items. Only Ubuntu
  24.04 was run. An Ubuntu 22.04 host image (`lab/host/Dockerfile.jammy`) and eight conditions
  for it (`jammy_*` in `src/logcanary/conditions.py`) are defined but were never built or run.
  No Windows VM or Splunk licence was available in this environment.
- **Phase 2, "rules that died silently".** Not built. The `blind_pct` metric models one scheduled
  rule (5 minute interval, 6 minute look-back) against the measured arrival times, which is the
  arithmetic part of that question, not a test of real Sigma rules.
- **Elastic Agent and Logstash.** Filebeat stands in for the Elastic side; no Fleet-managed agent.
- **Security on.** Elasticsearch runs with security off (no TLS, no auth). TLS adds handshake and
  retry paths that are not tested.

**Measurement limits:**

- **Settle time.** The guide asks for 10 minutes of no new arrivals. Runs settle after 20 to 90 s
  and the final numbers come from a second pass over every run at the end of the matrix. A canary
  that arrived after that second pass would be counted as lost.
- **Sample sizes.** 2 to 5 repeats per condition. The 95% intervals on loss are wide; read the
  worst run as well as the mean.
- **Elasticsearch was throttling indexing during 56 of 88 runs**, because the nearly full build
  disk held its merges back. Those runs are marked in every table ("Runs during ES throttling");
  compare conditions with that in mind (`docs/what-went-wrong.md`, item 19).
- **"Lost before disk" undercounts what was on disk under aggressive rotation.** The host probe
  counts canaries still in `/var/log/syslog*` and the journal after the run. In `disk_pressure`
  (`rotate 1` and an 8 MB journal cap) older files are gone by then, so its `lost_before_disk`
  includes canaries that were written and later rotated away; Filebeat indexed every file-path
  canary in that condition.
- - **Two sessions.** Most runs are from 14 November 2026; `mangling`, both clock conditions,
  `rotate_stock`, one `rotate_copytruncate` run and the tuned `es_down_120` and `disk_pressure` runs were run on 20 November on the same
  images and configs. Load from other work on the machine differed between the two days.
- **Raw files are not in the repository.** Ledgers and arrivals (about 76 MB) are kept out of git
  and listed by SHA-256 in `results/raw_sha256.txt`. The tables and summary follow from the
  committed per-run results; the raw files are needed to recompute those results or redraw the
  latency, timeline and clock charts.
- **Shared machine.** Other builds were running on the same 4 CPUs. Latency in particular would be
  lower on an idle machine, and a busy moment can make one repeat look worse than another.
- **All three shippers read at once.** They compete for CPU and disk during bursts; each one alone
  might do better.
- **The writer is one Python process.** "As fast as possible" bursts are as fast as that process
  can call `syslog(3)` and `sendto(2)`; a C program could push harder.
- **"Silent" is a text match.** A component counts as having reported loss if a log line at
  warning level or above matches words like drop, discard, lost, suppress, rejected, not retried.
  A line could report loss in other words; samples of every component's lines are kept in each
  run's `alerts.json` so this can be re-read.
- **Default configs are a judgement.** "Default" means the smallest documented config that works;
  others would pick other defaults. The tuned set shows what changes when the reliability settings
  are turned on, and both are reported.
