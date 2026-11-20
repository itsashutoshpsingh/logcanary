"""Keep the Elasticsearch log lines that matter for reading the results: node start and stop,
merges held back for lack of disk space, and indexing throttled because merges fell behind.

    docker logs lc-es 2>&1 | python3 scripts/es_events.py > results/es_events.jsonl
    gzip -nf results/es_events.jsonl

`logcanary report` reads results/es_events.jsonl.gz to mark runs that overlapped a throttling window.
"""

import json
import re
import sys

KEEP = re.compile(r"^(started |stopping \.\.\.)|throttling indexing|insufficient disk space|indices\.merge\.disk")

for line in sys.stdin:
    try:
        d = json.loads(line)
    except ValueError:
        continue
    if KEEP.search(d.get("message", "")):
        print(json.dumps({k: d.get(k) for k in ("@timestamp", "log.level", "log.logger", "message")}))
