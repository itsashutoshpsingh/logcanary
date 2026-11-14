# Prior art

Searched on 14 November 2026: GitHub code and issues (through a developer search index, since
github.com pages were not reachable from the build machine), general web search, and vendor
documentation. Queries: `log canary siem`, `siem heartbeat sequence`, `log completeness test`,
`log loss measurement elastic`, `end to end log delivery test`, `"log loss" SIEM measurement`,
`log shipper benchmark data loss`, `TrackMe data source monitoring`, `Sentinel data connector health`.

I could not find an open tool that writes numbered events through a host's own logging path
(syslog, journald), keeps the ground truth on the host, and reconciles it against what the SIEM
indexed under injected faults, with field damage, clock skew and "did anything alert" recorded per
run. The closest work, and how logcanary differs:

| Work | What it does | Difference |
|---|---|---|
| [VictoriaMetrics, "Benchmarking Kubernetes Log Collectors" (2026)](https://victoriametrics.com/blog/log-collectors-benchmark-2026/) | Load test of vlagent, Vector, Fluent Bit, Filebeat, fluentd, OpenTelemetry Collector in Kubernetes; measures log loss rate, throughput, CPU, memory; found incomplete records at file rotation in Fluent Bit and Vector and loss in Filebeat and fluentd before 10k logs/s. | The closest. It measures shipper throughput and loss from container log files under load. It does not inject faults (partitions, SIEM outage, restarts, clock jumps), does not go through syslog or journald, and does not ask whether anything alerted. |
| [vectordotdev/vector-test-harness](https://github.com/vectordotdev/vector-test-harness) | Vector's own performance and correctness tests (disk buffer persistence, file rotation, restarts) used for the comparisons in Vector's docs. | A vendor's harness for shipper correctness cases, not a source-to-SIEM measurement; archived. |
| [eddiechu/event-log-load-test](https://github.com/eddiechu/event-log-load-test) | PowerShell: write a labelled batch of Windows events, then compare the count in Event Viewer, the SIEM and a listener. | Same idea at the smallest scale: counts only, Windows only, no faults, no latency, fidelity or skew. |
| [elastic/logstash#3691](https://github.com/elastic/logstash/issues/3691) | A bug report that used sequence numbers to show loss between two Logstash instances under back-pressure. | One-off reproduction, not a tool. |
| [Microsoft Sentinel data connector health](https://learn.microsoft.com/en-us/azure/sentinel/monitor-data-connector-health) | `SentinelHealth` table: connector status changes and failures; transient errors logged after 60 minutes. | Arrival-side: sees a connector fail, cannot see events that never left a host. |
| [TrackMe for Splunk](https://docs.trackme-solutions.com/latest/product_guide/components_dsm.html) | Tracks per-source delay (time since last event), latency (`_indextime - _time`) and volume outliers. | Arrival-side: compares a feed with its own history, so partial loss inside a still-flowing feed and loss that happens every day look normal. |

Not checked: whether Elastic, Splunk or Cribl ship a free source-side canary feature. The search
tool's quota ran out before those queries; this is an open item in `docs/what-went-wrong.md`.
What the lab itself shows is narrower: none of the three shippers, rsyslog, journald or
Elasticsearch as configured here raises an alert that reaches the SIEM when canaries go missing
(see the alerts columns in `results/table.md`).

What logcanary does *not* add: it is one lab. The VictoriaMetrics benchmark is better on load
and resource use; this repository is narrower and deeper on faults, field damage and silence.
