# What went wrong

Every miss, dead end and limit met while building this, and what each does to the numbers.

## Building the lab

1. **The guide's Debian 12 host could not be built.** The build machine's network blocks
   `deb.debian.org` and every Debian mirror tried; `archive.ubuntu.com` was reachable. The host
   under test is Ubuntu 24.04 LTS instead. Effect: the rsyslog and systemd versions are Ubuntu's
   (8.2312 and 255), and Ubuntu's stock rsyslog writes RFC 3339 timestamps with microseconds,
   which Debian 12's also does. Results say "Ubuntu 24.04" everywhere.
2. **Docker Hub rate-limited a pull** (HTTP 429). The Ubuntu base image comes from Google's Docker
   Hub mirror (`mirror.gcr.io`), pinned by digest; same image.
3. **journald exited when told to flush to disk.** Without systemd, I first sent journald SIGUSR1
   (what `systemd-journal-flush` does). journald then tried to delete its runtime journal under
   `/run`, refused because `/run` is not tmpfs in a container ("Attempted to remove disk file
   system ... and we can't allow that"), and its event loop exited. Fix: create
   `/run/systemd/journal/flushed` before start, which makes journald write to `/var/log/journal`
   from the first entry. No run used the broken setup.
4. **journald exited once more during setup** with "Failed to run event loop: Invalid argument",
   right after a clock-offset change and two "Under memory pressure, flushing caches" messages.
   I could not reproduce it then (journald survived the clock jumps tried during setup), but it
   came back in every +2 h run on 20 November (item 14). In
   response the host got a supervisor that restarts journald and rsyslog within a second, as
   systemd's `Restart=` would, and logs every restart with a true timestamp. Each run's
   `meta.json` lists any restart (`host_supervisor`), so an unplanned journald death would show up
   there and as loss on the journald path, not be hidden.
5. **rsyslog ignored the fake clock.** `imuxsock` stamps messages with the kernel's receive time
   by default (`SysSock.UseSysTimeStamp="on"`), which libfaketime cannot move. I turned that off
   for every run. Effect: rsyslog stamps with its own clock; the difference from the kernel's
   receive time is microseconds, and it is the same in every condition.
6. **Shippers reported the container ID as the host name.** In the first test, Filebeat's
   `host.name` and Vector's `host` were the shipper container's random ID. Shippers installed on a
   host see the host's name, so the shipper containers now carry the hostname `lab-host`. No
   measured run used the old setting; the field-fidelity check would otherwise have failed every
   Filebeat file-path canary for a lab artefact.
7. **logrotate refused to run** ("parent directory has insecure permissions"): Ubuntu's global
   `/etc/logrotate.conf` sets `su root syslog`, and my standalone configs did not. Added; caught
   before any measured run.

## Measuring

8. **Settle time.** The guide's settle rule is "no new arrivals for 10 minutes". Waiting that long
   after every one of about 90 runs would have added 15 hours. Runs settle after 20 to 90 s; then
   every condition gets a second, final reconcile once its last run is at least 15 minutes old,
   and the published numbers come from that pass. Canaries that arrived between the two passes
   are counted per run (`late_after_settle` in `results/runs.csv`). After the final pass the
   condition's documents are deleted from Elasticsearch to keep the lab disk small, so a run can
   no longer be re-queried; its raw arrivals stay in `arrivals.csv.gz`.
9. **Disk.** At the start, the shared build disk had 11 to 12 GB free. Projected Elasticsearch
   storage for the full matrix was about 5 GB, most of it from `disk_pressure` (200 canaries a
   second of 2 KB for 200 s). I halved that condition to 100 a second and 20,000 canaries before it
   ran, and added the pruning above. Its journal cap (8 MB) and rotation schedule are unchanged,
   so the backlog still exceeds what the host keeps.
10. **The matrix was restarted once**, during the baseline, to load the finalize-and-prune code.
    The run in progress at that moment was discarded and repeated; the resume logic deletes any
    run directory without a result.
11. **Vector was OOM-killed in every "as fast as possible" burst, and stayed dead.** In the first
    three `burst_max` runs (about 18,000 to 21,000 canaries a second on each path) Vector exceeded
    its 256 MB limit and the kernel killed it. The shipper containers had no restart policy, so it
    stayed down until the next run's preflight, which then recreated all three shippers (and reset
    the host logs) instead of just starting the dead one. Measured loss for Vector in those runs
    was 76.3% and 27.3% (file / journal, run 1) and 49.7% and 55.2% on journald in runs 2 and 3
    (`result.json` in each discarded run): a mix of the
    crash and of nobody restarting it. A real host restarts a crashed agent (systemd `Restart=`,
    a Kubernetes DaemonSet), so I added `restart: on-failure` to the shippers (Docker does not
    apply it to a deliberate `docker kill`, so the crash condition keeps its 10 s downtime),
    changed preflight to restart a dead shipper rather than recreate it, and reran `burst_max`.
    The three discarded runs are kept, unchanged, in
    `results/discarded/burst_max_no_restart_policy/` and are not in any table. Every run now records
    each shipper's restart count before and after (`restarts_before`, `states` in `meta.json`).
12. **Prior-art search ran out of quota** on 14 November before I could check whether Elastic,
    Splunk or Cribl offer a free source-side canary feature. Checked on 20 November instead; what
    I found is in `docs/prior_art.md`.

## Finishing the matrix (20 November)

13. **Thirteen runs failed on 14 November and were rerun six days later.** Between 17:07 and
    17:35 UTC every run of `mangling` (3), `clock_fwd_2h` (3), `clock_back_10m` (3),
    `rotate_stock` (3) and the first run of `rotate_copytruncate` failed after the writer had
    finished and before the ledger was exported, so each left an empty run directory and no
    result. The writer had done its part (the 13 SQLite ledgers were still on the host and the
    canaries were in Elasticsearch), but the traceback went to a console log that was not kept,
    so I do not know which step failed. I did not rebuild results from those leftovers: they have
    no fault log, counters or host probe. On 20 November, on the same images, configs and host
    container, all 13 were run again and none failed. The resume logic now fills the repeat
    numbers a failed run left free instead of appending after the last one, which would have
    given `rotate_copytruncate` two runs called `r3`. Effect: those five conditions are measured
    on a different day from the rest, with whatever else the shared machine was running then.
14. **journald died over and over while the host clock was +2 h.** In every `clock_fwd_2h` run
    journald exited about once a second for the whole jump window with
    `Failed to run event loop: Invalid argument` and the supervisor restarted it each time
    (`host_supervisor` in `meta.json`). The writer's `sendto(2)` to the journal socket was refused
    for most canaries in that window (`send_err` in the ledger) and they never reached the
    journal, which is the journald-path loss in that row. It is the same error as item 4. journald
    reads the time through libfaketime here, and its event loop also uses timers that libfaketime
    may not move consistently, so this may be an artefact of faking the clock rather than what
    journald does when a real host clock jumps. I report the row as measured and do not use its
    loss as a headline figure, though its 9 silent streams are part of the silent count in the
    headline; it needs a VM with a real clock change to settle.
15. **The lab was left half-finalized when the first session stopped.** The 9 tuned runs and two
    `rotate_copytruncate` runs had only their at-settle reconcile. Their final reconcile ran on
    20 November against the same Elasticsearch volume. When the Docker daemon came back, the
    three shippers restarted by themselves (`restart: on-failure`) with the tuned configs while
    Elasticsearch was still stopped; I stopped them within about a minute, before Elasticsearch
    started and before that final reconcile, so they could not add documents to any run.
16. **The committed tables were stale.** `results/*.csv`, `results/table.md` and the charts had
    been generated at 14:56 and 15:37 on 14 November, before half the matrix had run, and
    `results/summary.json` did not exist. All of them are now rebuilt from every run.
17. **Not run.** The Ubuntu 22.04 host (eight conditions defined in
    `src/logcanary/conditions.py` as `jammy_*`, and `lab/host/Dockerfile.jammy`) was never built
    or run; there are no 22.04 numbers. Every condition of the Ubuntu 24.04 matrix, default and
    tuned, did run; `es_down_120_tuned` and `disk_pressure_tuned` for the first time on 20 November.
18. **Raw files are not in git.** The per-run ledgers and arrivals add up to about 76 MB. They
    are listed with SHA-256 hashes in `results/raw_sha256.txt`; git holds each run's compact files
    (`meta.json`, `alerts.json`, `result.json`, `result_settle.json`, shipper logs). Every table,
    `results/summary.json` and the README follow from those, and CI checks it
    (`logcanary report --check`). The charts built from raw arrivals (latency distribution,
    timelines, clock skew) can only be redrawn with the raw files.
19. **Elasticsearch throttled indexing for part of the matrix, because the disk was nearly full.**
    Found on 20 November when a prune step hung: Elasticsearch 8.19 holds merges back when free
    space on its data disk is below its merge high watermark (95% used by default, about 13.5 GB
    on this 252 GiB disk), and the shared build disk had about 4 to 11 GB free. From 14:16 on
    14 November it logged "insufficient disk space available to execute [merges]" every 5 s; once
    merges queued up it logged "now throttling indexing" (one indexing thread per shard) from
    14:29 to 16:07 and from 17:11 until the session ended on 14 November, and from 01:16 to 01:46
    on 20 November. Those log lines are kept in `results/es_events.jsonl.gz`, and every run that
    overlapped a throttling window is marked (`es_throttled` in `results/runs.csv`, "Runs during
    ES throttling" in `results/table.md`): 56 of the 88 runs, including every run of `burst_4k`,
    `shipper_restart`, `shipper_crash`, `partition_60`, `partition_300`, `daemon_crash`,
    `disk_pressure` and the three tuned conditions run on 14 November. Not affected: `baseline`,
    `es_down_600`, `es_freeze_120`, `sizes`, `mangling`, `clock_fwd_2h`, `es_down_120_tuned` and
    `disk_pressure_tuned`. Effect: ingest latency in the marked runs is likely higher than an
    unthrottled node would give, and back-pressure reached the shippers sooner, so their loss may
    be partly this and not only the injected fault. I set `indices.merge.disk.watermark.high` to
    500 MB at 01:46 on 20 November (now part of `logcanary lab-up`); later runs were not
    throttled. I did not rerun the marked runs: that is most of the matrix, and the disk and time
    were not there. They are marked instead.
20. **The machine restarted once more before the last final reconcile.** The three
    `disk_pressure_tuned` runs finished at 02:43 on 20 November and the machine went down before
    their final reconcile. When Docker came back the shippers restarted by themselves again, with
    Elasticsearch stopped; I stopped them within seconds, then started Elasticsearch alone and ran
    the final reconcile about eight hours after those runs.
