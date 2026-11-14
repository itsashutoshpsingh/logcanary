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
   I could not reproduce it (journald survived the same clock jumps repeatedly afterwards). In
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
11. **Prior-art search ran out of quota** before I could check whether Elastic, Splunk or Cribl
    offer a free source-side canary feature. `docs/prior_art.md` says so instead of guessing.
