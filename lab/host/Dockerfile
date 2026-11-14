# Host under test: Ubuntu 24.04 LTS with the stock rsyslog and systemd-journald as the OS logging path.
# Package versions are pinned. The build needs an HTTPS route to archive.ubuntu.com; if your network
# re-signs TLS, put its CA bundle in lab/host/ca/ca.crt (ignored by git).
FROM mirror.gcr.io/library/ubuntu:noble-20261024.1@sha256:fe81560990fae86dc4743202b2cb4d3df98d0bcf949173cecef15ce1127ef852
COPY ca/ /tmp/ca/
RUN set -eux; \
    sed -i 's#http://#https://#g' /etc/apt/sources.list.d/ubuntu.sources; \
    if [ -f /tmp/ca/ca.crt ]; then echo 'Acquire::https::CAInfo "/tmp/ca/ca.crt";' > /etc/apt/apt.conf.d/99ca; fi; \
    apt-get update; \
    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
      rsyslog=8.2312.0-3ubuntu9.4 \
      systemd=255.4-1ubuntu8.18 \
      logrotate=3.21.0-2build1 \
      faketime=0.9.10-2.1 \
      python3=3.12.3-0ubuntu2.1 \
      procps; \
    rm -rf /var/lib/apt/lists/* /etc/apt/apt.conf.d/99ca /tmp/ca; \
    systemd-machine-id-setup; \
    mkdir -p /var/log/journal /var/lib/logcanary /etc/logcanary; \
    # Two changes to stock rsyslog.conf: a container cannot read the kernel log, and imuxsock must
    # stamp messages with rsyslog's own clock (not the kernel receive time) so the clock-skew
    # fault can move it. See docs/method.md.
    sed -i 's/^module(load="imklog"/# &/' /etc/rsyslog.conf; \
    sed -i 's/^module(load="imuxsock")/module(load="imuxsock" SysSock.UseSysTimeStamp="off")/' /etc/rsyslog.conf; \
    grep -q 'UseSysTimeStamp="off"' /etc/rsyslog.conf
COPY logrotate/ /etc/logcanary/logrotate/
COPY entrypoint.sh lc-daemon /usr/local/bin/
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
