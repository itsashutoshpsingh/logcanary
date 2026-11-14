#!/bin/sh
# Starts the host's logging daemons and supervises them like systemd would (journald and rsyslog
# both restart on failure). Every restart is logged with a true-time stamp.
# The canary writer runs via `docker exec`.
set -eu
mkdir -p /run/systemd/journal /run/logcanary /var/log/journal /var/spool/rsyslog /var/lib/logcanary
touch /var/log/syslog && chown syslog:adm /var/log/syslog
# Host clock offset in seconds, read by libfaketime in both daemons and by the writer.
# The clock-skew fault rewrites it; "+0" means the true time.
echo "+0" > /run/logcanary/faketime
log=/var/lib/logcanary/supervisor.log
while true; do
  for d in journald rsyslog; do
    if ! /usr/local/bin/lc-daemon status "$d" >/dev/null 2>&1; then
      echo "$(date -u +%Y-%m-%dT%H:%M:%S.%NZ) start $d" >> "$log"
      /usr/local/bin/lc-daemon start "$d" || echo "$(date -u +%Y-%m-%dT%H:%M:%S.%NZ) failed $d" >> "$log"
    fi
  done
  sleep 1
done
