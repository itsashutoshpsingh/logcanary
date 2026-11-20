# Hand checks

Checks made by hand against the lab while the documents were still in Elasticsearch, to make sure
the reconciler's numbers mean what they say. Raw command output is pasted unchanged.

## 1. "Lost" means absent from the index and present on disk (partition_60, repeat 5)

The reconciler reported 2,450 canaries lost by Fluent Bit on the file path in run `f3f5ecfdcf03`,
one range, seq 998 to 3447. `scripts/handcheck.sh` asks each index for the exact phrase
`run=<run> src=syslog seq=<n> ts` and greps the host's `/var/log/syslog`:

```
$ scripts/handcheck.sh f3f5ecfdcf03 syslog 997 998 2000 3447 3448
== seq 997
  lc-filebeat: 1 document(s)
  lc-fluentbit: 1 document(s)
  lc-vector: 2 document(s)
  on the host's disk: 1 line(s)
== seq 998
  lc-filebeat: 1 document(s)
  lc-fluentbit: 0 document(s)
  lc-vector: 2 document(s)
  on the host's disk: 1 line(s)
== seq 2000
  lc-filebeat: 1 document(s)
  lc-fluentbit: 0 document(s)
  lc-vector: 1 document(s)
  on the host's disk: 1 line(s)
== seq 3447
  lc-filebeat: 1 document(s)
  lc-fluentbit: 0 document(s)
  lc-vector: 1 document(s)
  on the host's disk: 1 line(s)
== seq 3448
  lc-filebeat: 1 document(s)
  lc-fluentbit: 1 document(s)
  lc-vector: 1 document(s)
  on the host's disk: 1 line(s)
```

The boundaries match the reconciler's range exactly (997 and 3448 arrived, 998, 2000 and 3447
did not), every canary is on the host's disk, and Vector's two documents for 997 and 998 are
the duplicates the reconciler counted for Vector in that run. Fluent Bit's own log for that
run has 100 lines saying a chunk "cannot be retried" (`results/runs/partition_60/r5-f3f5ecfdcf03/fluentbit.log.gz`).

## 2. copytruncate loss is per shipper, not on the host (rotate_copytruncate, repeat 2)

The reconciler reported 39 canaries lost by Filebeat on the file path in run `a06da9caa754`
(seq 1462 to 1500) and 1 lost by Vector (seq 1500); Fluent Bit lost none. Checked on
20 November 2026, after the final reconcile, with the same exact-phrase query per index (the
host's own log files had been reset by then, so only the indexes are queried):

```
$ run=a06da9caa754; for seq in 1461 1462 1480 1499 1500 1501; do echo "== seq $seq"
    for idx in lc-filebeat lc-fluentbit lc-vector; do
      n=$(curl -s "localhost:9200/$idx/_count" -H 'content-type: application/json' \
          -d "{\"query\":{\"match_phrase\":{\"message\":\"run=$run src=syslog seq=$seq ts\"}}}" \
          | sed 's/.*"count":\([0-9]*\).*/\1/')
      echo "  $idx: $n document(s)"; done; done
== seq 1461
  lc-filebeat: 1 document(s)
  lc-fluentbit: 1 document(s)
  lc-vector: 1 document(s)
== seq 1462
  lc-filebeat: 0 document(s)
  lc-fluentbit: 1 document(s)
  lc-vector: 1 document(s)
== seq 1480
  lc-filebeat: 0 document(s)
  lc-fluentbit: 1 document(s)
  lc-vector: 1 document(s)
== seq 1499
  lc-filebeat: 0 document(s)
  lc-fluentbit: 1 document(s)
  lc-vector: 1 document(s)
== seq 1500
  lc-filebeat: 0 document(s)
  lc-fluentbit: 1 document(s)
  lc-vector: 0 document(s)
== seq 1501
  lc-filebeat: 1 document(s)
  lc-fluentbit: 1 document(s)
  lc-vector: 1 document(s)
```

The boundaries match the reconciler's ranges exactly. The run's own probe counted all 4,000
canaries in `/var/log/syslog*` on the host (`probe_on_disk` in `meta.json`), and Fluent Bit
indexed every one, so the lines were on disk. The ledger puts seq 1462 at 29.35 s and seq 1500
at 30.10 s after the writer started; `logrotate -f` ran from 30.00 s to 30.13 s
(`faults` in `meta.json`). Lines a shipper had not read yet when the file was truncated exist
only in the copy, `/var/log/syslog.1`, which none of the three is configured to read. No
shipper, rsyslog or journald wrote anything about it (`alerts.json`: all `quiet`).

## 3. A +2 h host clock reaches the SIEM's event time on the file path (clock_fwd_2h, repeat 1)

Run `b7082692eed5`, checked on 20 November 2026 while its documents were still indexed. The
host clock (libfaketime, journald and rsyslog only) was +2 h from 30 s to 90 s after the writer
started. Canary seq 300 was written before the jump, seq 1000 inside it. From
`ledger.csv.gz` (true time `ts_wall_ns`, host clock `ts_host_ns`, writer's send error):

```
journald,300,1795136730241448161,1795136730241448161,256,plain,
journald,1000,1795136765241464269,1795143965241464269,256,plain,ConnectionRefusedError
syslog,300,1795136730241339040,1795136730241339040,256,plain,
syslog,1000,1795136765241354834,1795143965241354834,256,plain,
```

`1795136765.241` is 01:06:05.241 UTC; `1795143965.241` is 03:06:05.241. Each index asked for the
exact phrase `run=b7082692eed5 src=<src> seq=<n> ts`, returning `@timestamp` and `event.ingested`:

```
300 syslog lc-filebeat: {"@timestamp":"2026-11-20T01:05:30.241468Z","event":{"ingested":"2026-11-20T01:05:35.613676340Z"}}
300 syslog lc-fluentbit: {"@timestamp":"2026-11-20T01:05:30.241468Z","event":{"ingested":"2026-11-20T01:05:31.212906464Z"}}
300 syslog lc-vector: {"@timestamp":"2026-11-20T01:05:30.241468Z","event":{"ingested":"2026-11-20T01:05:30.866934042Z"}}
300 journald lc-filebeat: {"@timestamp":"2026-11-20T01:05:30.241Z","event":{"ingested":"2026-11-20T01:05:35.613013765Z"}}
300 journald lc-fluentbit: {"@timestamp":"2026-11-20T01:05:30.241Z","event":{"ingested":"2026-11-20T01:05:31.215172937Z"}}
300 journald lc-vector: {"event":{"ingested":"2026-11-20T01:05:30.867087707Z"},"@timestamp":"2026-11-20T01:05:30.241487Z"}
1000 syslog lc-filebeat: {"@timestamp":"2026-11-20T03:06:05.241692Z","event":{"ingested":"2026-11-20T01:06:16.275716699Z"}}
1000 syslog lc-fluentbit: {"@timestamp":"2026-11-20T03:06:05.241692Z","event":{"ingested":"2026-11-20T01:06:06.212732962Z"}}
1000 syslog lc-vector: {"@timestamp":"2026-11-20T03:06:05.241692Z","event":{"ingested":"2026-11-20T01:06:05.895327551Z"}}
1000 journald lc-filebeat: {}
1000 journald lc-fluentbit: {}
1000 journald lc-vector: {}
```

On the file path the SIEM stores the host's wrong time: indexed at 01:06, stamped 03:06, the
+7,200,004.5 ms skew in `result.json`. On the journal path seq 1000 is in no index at all: the
writer's `sendto(2)` to journald's socket was refused, because journald was not running.
Under the +2 h clock journald exited 58 times with `Failed to run event loop: Invalid argument`
(its stderr on the host) and the supervisor restarted it each time (`host_supervisor` in
`meta.json`); 1,147 journald canaries got `ConnectionRefusedError` and 1,175 never reached the
journal (`lost_before_disk`). See `docs/what-went-wrong.md` for why this may be a libfaketime
artefact rather than journald behaviour on a real clock jump.
