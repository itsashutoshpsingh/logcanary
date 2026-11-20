#!/bin/sh
# Hand check of one run while its documents are still in Elasticsearch: for a few sequence numbers
# the reconciler called lost for one shipper, ask Elasticsearch directly (exact phrase, per index)
# and grep the host's own files. Usage: scripts/handcheck.sh RUN SRC SEQ...
set -eu
run=$1; src=$2; shift 2
for seq in "$@"; do
  phrase="run=$run src=$src seq=$seq ts"
  echo "== seq $seq"
  for idx in lc-filebeat lc-fluentbit lc-vector; do
    n=$(curl -s "localhost:9200/$idx/_count" -H 'content-type: application/json' \
        -d "{\"query\":{\"match_phrase\":{\"message\":\"$phrase\"}}}" | sed 's/.*"count":\([0-9]*\).*/\1/')
    echo "  $idx: $n document(s)"
  done
  if [ "$src" = syslog ]; then
    n=$(docker exec lc-host sh -c "cat /var/log/syslog /var/log/syslog.1 2>/dev/null | grep -c 'run=$run src=syslog seq=$seq '" || true)
  else
    n=$(docker exec lc-host sh -c "journalctl -D /var/log/journal -o cat SYSLOG_IDENTIFIER=logcanary | grep -c 'run=$run src=journald seq=$seq '" || true)
  fi
  echo "  on the host's disk: $n line(s)"
done
