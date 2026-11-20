# Method

## The question

Every detection assumes the log arrived. Arrival-side health checks (connector health, "time
since last event") cannot see events that never left the host, or a feed that keeps flowing
while part of it is missing. logcanary keeps the ground truth on the host and counts again in
the SIEM.

## Lab

Everything runs in Docker on one machine (4 CPUs, 16 GB RAM shared with other workloads; the lab
is capped at 3,008 MB of container memory). Exact images and digests are in
[`lab/docker-compose.yml`](../lab/docker-compose.yml); host packages are pinned in
[`lab/host/Dockerfile`](../lab/host/Dockerfile).

| Part | What | Version |
|---|---|---|
| Host under test | Ubuntu 24.04 LTS container, hostname `lab-host`, 256 MB | `ubuntu:noble-20261024.1` |
| Syslog daemon | rsyslog, Ubuntu's stock `rsyslog.conf` and `50-default.conf` | 8.2312.0-3ubuntu9.4 |
| Journal | systemd-journald, stock `journald.conf` (all defaults) | 255.4-1ubuntu8.18 |
| Shipper 1 | Filebeat, `filestream` + `journald` inputs, 256 MB | 8.19.25 |
| Shipper 2 | Fluent Bit, `tail` + `systemd` inputs, 192 MB | 5.1.5 |
| Shipper 3 | Vector, `file` + `journald` sources, 256 MB | 0.61.0 |
| SIEM | Elasticsearch single node, 1 GB heap, 2 GB limit, security off | 8.19.25 |

The shippers run as separate containers that mount the host's `/var/log` read-only and carry the
host's hostname, the way a DaemonSet or sidecar agent does. They read the same two sources at the
same time and each writes to its own index (`lc-filebeat`, `lc-fluentbit`, `lc-vector`), so every
run measures all three under the same conditions. All three share one Elasticsearch ingest
pipeline ([`lab/es/pipeline.json`](../lab/es/pipeline.json)) that:

- sets `event.ingested` to the ingest time (`_ingest.timestamp`);
- moves Fluent Bit's `log` and journald's `MESSAGE` into `message`;
- for lines from the syslog file, parses the RFC 3339 timestamp, host and program at the start of
  the line and uses that timestamp as `@timestamp` (what Elastic's own system integration does).

## Two log paths

| Path | Writer call | Daemon | On disk | Shipper input |
|---|---|---|---|---|
| syslog | `syslog(3)` from Python's `syslog` module | rsyslog `imuxsock` on `/dev/log` | `/var/log/syslog` | file tail |
| journald | native journal protocol datagram on `/run/systemd/journal/socket` (what `sd_journal_send` does) | systemd-journald | `/var/log/journal/<machine-id>/` | journal reader (`journalctl` or libsystemd) |

Every canary is written once on each path, so each path sees the stated rate and the host sees
twice that.

## Canary and ledger

A canary is one log line ([`src/logcanary/message.py`](../src/logcanary/message.py)):

```
lc1 run=<12 hex> src=<syslog|journald> seq=<n> ts=<host clock, ns> kind=<kind> |<body>| crc=<crc32>
```

The header comes first so a cut or mangled message can still be identified. The CRC covers every
byte before ` crc=`. Bodies come in five kinds: `plain`, `multiline` (a Java stack trace with real
newlines and tabs), `unicode` (accents, a combining mark, CJK, Arabic, Hebrew, emoji, a zero-width
space, a no-break space), `control` (tab, carriage return, ANSI colour codes, bell, quotes,
backslash, printf directives) and `long`.

The guide proposed a JSON payload. I used a key=value header with a free-text body instead: JSON
cannot carry a raw newline or tab, which is exactly what the field-damage tests need to send.

The ledger ([`src/logcanary/writer.py`](../src/logcanary/writer.py)) is a SQLite table on the host
with one row per canary and path: `run, cond, src, seq, ts_wall_ns, ts_mono_ns, ts_host_ns,
size_bytes, kind, sha1, send_err`. `ts_wall_ns` is the true time (the writer itself is never given
a fake clock), `ts_mono_ns` is monotonic, and `ts_host_ns` is what the host clock said and what
the payload carries. They differ only in the clock-skew conditions. Each run's ledger is exported
to `results/runs/<condition>/r<n>-<run>/ledger.csv.gz`.

## Reconciler

[`src/logcanary/reconcile_es.py`](../src/logcanary/reconcile_es.py) pulls every document whose
`message` contains `run=<run>` from `lc-*` with the scroll helper (`helpers.scan`), never a plain
search, because a plain search stops at 10,000 hits and would invent loss. It parses the canary
header and checks the CRC in Python. Arrivals go to `arrivals.csv.gz` next to the ledger.

**Settle.** After the writer finishes and every fault is undone, the runner polls document counts
every 5 s. It stops when no shipper's count has moved for 20 s if every shipper holds at least as
many documents as were sent, and for 90 s otherwise (longer than Filebeat's 60 s maximum retry
backoff). The guide asks for 10 minutes of no new arrivals; 90 s is shorter, so after the whole
matrix `logcanary reconcile` queries Elasticsearch again for every run. Results in this repository
are from that final pass, which ran at least 15 minutes after each run's writer finished (hours
for early runs, six days for the runs left unfinalized when the first session stopped). Canaries
that arrived between the settle point and the final pass are counted per run in
`late_after_settle` (`results/runs.csv`).

## Metric definitions

From the project guide, word for word:

- **Loss %** = (sent minus distinct seq arrived) / sent, measured after a settle time of 10 minutes with no new arrivals.
- **Duplicates** = arrived documents minus distinct seq arrived.
- **Ingest latency** = SIEM index time minus `ts_src_ns`. In Elasticsearch use `event.ingested`; if your pipeline does not set it, add an ingest pipeline with a `set` processor writing `{{_ingest.timestamp}}`.
- **Clock skew** = SIEM `@timestamp` minus `ts_src_ns`. Non-zero skew means the pipeline changed the event time.
- **Fields intact %** = arrived canaries where every expected field is present with the right type and `chk` verifies.
- **Missed-by-lookback %** = arrived canaries whose ingest latency exceeds a rule lookback of 5 minutes. These events are in the SIEM but a scheduled rule would never see them.
- **Silent** = yes if no component (journald, auditd, shipper, SIEM) raised a visible warning about the loss. Record where a warning did appear (for example journald "Suppressed N messages").

How they are applied here ([`src/logcanary/metrics.py`](../src/logcanary/metrics.py)):

- `ts_src_ns` is the ledger's **true** write time (`ts_wall_ns`). Settle: see above.
- **Latency** uses the first copy of each canary to arrive.
- **Fields intact** uses the fields in [`src/logcanary/fidelity.toml`](../src/logcanary/fidelity.toml):
  for each shipper and path, a host field that must equal `lab-host`, a program field that must
  equal `logcanary`, an `@timestamp` that parses, and a message whose CRC verifies byte for byte.
  The types are fixed by the index template, so "right type" reduces to "present and equal".
  Two weaker grades are reported beside it: **exact** (message CRC verifies) and **recoverable**
  (the CRC verifies after undoing rsyslog's `#ooo` control-character escapes).
- **Missed by a scheduled rule.** The guide's cut ("latency over 5 minutes") is reported as
  `late_5m_pct`. I also model the rule properly: Elastic Security's default schedule runs every
  5 minutes and searches `@timestamp` from now-6m to now. An event becomes searchable at
  `event.ingested`; it is seen if some run time T satisfies `T >= ingested`, `T >= @timestamp` and
  `T - 6m <= @timestamp`. Over a uniformly random rule phase that probability is
  `clip((@timestamp + 6m - max(ingested, @timestamp)) / 5m, 0, 1)`. **Blind %** = share of *sent*
  canaries the rule never sees: lost ones plus the expected share of arrived ones it misses.
- **Silent** is per run, shipper and path: the run lost canaries, and neither the shipper's own
  log nor the host daemon on that path (rsyslog or journald) wrote a line saying events were
  dropped, discarded, suppressed, lost, rejected or not retried
  ([`src/logcanary/alerts.py`](../src/logcanary/alerts.py)). Warnings that do not mention loss
  ("connection refused") are recorded as `warn`, not as an alert about loss. The SIEM column is
  always no: nothing in these default pipelines sends a loss signal to Elasticsearch, so an
  analyst looking only at the SIEM sees nothing in every case. The shippers' own drop counters
  (Filebeat `/stats`, Fluent Bit `/api/v1/metrics`, Vector `internal_metrics`) are read before and
  after each run and reported as `shipper_counted_loss`. A shipper that crashed on its own (for
  example killed for running out of memory) is restarted by Docker's `on-failure` policy, as
  systemd or a Kubernetes DaemonSet would restart it; the number of such restarts per run is
  `shipper_crashes`. Deliberate restarts and kills by the fault injector do not count.
- **Lost before disk** = canaries in the ledger that never reached `/var/log/syslog*` or the
  journal, counted on the host after the run. These were lost by the host's own logging before any
  shipper could read them.
- **Gap rule.** What a SIEM-only rule could find without the ledger: holes between the lowest and
  highest sequence number that arrived. It cannot see loss at the start or the end of a stream.
- **Confidence intervals.** Loss % is averaged over repeats with a two-sided 95% Student t
  interval (n is 2 to 5 per condition, so the intervals are wide and say so).

## Faults

All faults are scheduled at offsets from the moment the writer starts and logged with true start
and end times in each run's `meta.json` ([`src/logcanary/faults.py`](../src/logcanary/faults.py),
[`src/logcanary/conditions.py`](../src/logcanary/conditions.py)).

| Fault | How |
|---|---|
| Burst | writer rate 1,000/s, 4,000/s, or as fast as one Python process can go |
| Shipper restart | `docker restart -t 10` on all three shippers (SIGTERM, then start) |
| Shipper crash | `docker kill -s KILL`, `docker start` 10 s later |
| Network partition | `docker network disconnect` of the shippers from the lab network, then reconnect |
| SIEM down | `docker stop` Elasticsearch, `docker start` later |
| SIEM frozen | `docker pause` Elasticsearch (sockets stay open, nothing answers), then unpause |
| Clock jump | the host's daemons run under libfaketime reading an offset file; the fault rewrites it |
| Log rotation | `logrotate -f` with Ubuntu's stock options, with `copytruncate`, or aggressive (`rotate 1`, no `delaycompress`) |
| Journal rotation and vacuum | SIGUSR2 to journald, `journalctl --vacuum-size=1M` |
| Daemon crash | SIGKILL rsyslog and journald; a supervisor restarts them within a second, as systemd would |
| Disk caps | journald `SystemMaxUse=8M`, `SystemMaxFileSize=2M`, plus aggressive rotation during a partition |

### Changes to stock configuration, and why

1. `imklog` is commented out in `rsyslog.conf`: a container cannot read the kernel log.
2. `imuxsock` gets `SysSock.UseSysTimeStamp="off"`. By default rsyslog stamps each message with
   the kernel's receive time, which no user-space fake clock can move, and the lab cannot move the
   shared kernel clock. With this off, rsyslog stamps with its own clock, so the clock fault can
   reach it. It applies to every run, faulted or not.
3. journald is started by a small supervisor instead of systemd, with the
   `/run/systemd/journal/flushed` marker set so it writes to `/var/log/journal` directly (what
   happens after `systemd-journal-flush.service` on a booted host).
4. logrotate's `postrotate` sends HUP to rsyslog directly instead of through `systemctl`.
5. Fluent Bit's `systemd` input uses `Read_From_Tail On` in the default set (as the official Helm
   chart does); without it and without an offset DB, each restart would re-ship the whole journal.

6. Elasticsearch's merge disk watermark (`indices.merge.disk.watermark.high`) is 500 MB, set by
   `logcanary lab-up`. This was added on 20 November; before it, low free disk made Elasticsearch
   hold merges back and throttle indexing (`docs/what-went-wrong.md`, item 19).

### Shipper settings: default and tuned

The **default** set is the smallest config from each project's documentation that reads both
sources into one index. The **tuned** set adds the reliability settings each project documents:

| Shipper | Tuned changes |
|---|---|
| Filebeat | none: it already keeps a registry on disk and retries without limit |
| Fluent Bit | offset DBs on both inputs, `storage.type filesystem`, `Mem_Buf_Limit 32MB`, `Retry_Limit False` |
| Vector | end-to-end `acknowledgements`, a 256 MB disk buffer |

## Matrix

See `logcanary list` and [`src/logcanary/conditions.py`](../src/logcanary/conditions.py): 20
default conditions (4 load, 12 faults, 2 field-fidelity, 2 clock) and 5 of them again with the
tuned set, 2 to 5 repeats each. One run of one condition writes to both paths and is read by all
three shippers, so each run yields six measured streams.

What actually ran: all 25 of those conditions, 88 runs and 1,561,800 canaries (each written once per path), 2 to 5 repeats each (`logcanary list`, `results/runs.csv`). Eight more conditions on an Ubuntu 22.04 host (`jammy_*`) are
defined but were not run. Three early `burst_max` runs were discarded (no restart policy on the
shippers; kept in `results/discarded/`, in no table). Thirteen runs that failed on 14 November
without writing a result were run again on 20 November. Details and reasons:
[`docs/what-went-wrong.md`](what-went-wrong.md).

## Files kept per run

`results/runs/<condition>/r<n>-<run>/` holds `meta.json` (parameters, fault times, settle trail,
shipper counters before and after, container states, host probe), `alerts.json` (what each
component logged about itself), the three shippers' own logs (`*.log.gz`), `result.json` (the
final reconcile) and `result_settle.json` (the first, at-settle reconcile). These are committed.
The raw `ledger.csv.gz` and `arrivals.csv.gz` (about 76 MB in all) are not; their SHA-256 hashes
are in `results/raw_sha256.txt` (`make check-raw` verifies a copy). `logcanary report` recomputes
`result.json` from the raw files when they are present and builds every table from the
`result.json` files either way; `logcanary report --check` (run in CI) fails if a committed table
or `results/summary.json` no longer follows from them.

## What is hand-checked

`docs/what-went-wrong.md` lists the checks made by hand: the settle logic against late arrivals,
the on-disk counts against `grep`, rsyslog's truncation point, and a sample of "lost" sequence
numbers looked up directly in Elasticsearch.
