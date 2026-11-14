from logcanary import alerts, reconcile_es
from logcanary.message import build


def test_classify_levels():
    fb = ['{"log.level":"info","message":"ok"}', '{"log.level":"error","message":"connection refused"}']
    assert alerts.classify_lines("filebeat", fb)["status"] == "warn"
    flb = ["[2026/11/14 14:12:50.009] [ warn] [engine] chunk 1-2.flb cannot be retried"]
    assert alerts.classify_lines("fluentbit", flb)["status"] == "loss"
    assert alerts.classify_lines("vector", ["2026-11-14T14:00:00Z  INFO vector: started"])["status"] == "quiet"
    assert alerts.classify_lines("journald", ["Suppressed 9982 messages from /"])["status"] == "loss"


def test_counters_and_delta():
    prom = ('vector_component_discarded_events_total{component_id="es",intentional="false"} 7 1794\n'
            'vector_component_discarded_events_total{component_id="other"} 100 1794\n')
    assert alerts.vector_counters(prom)["discarded"] == 7
    assert alerts.delta({"a": 5}, {"a": 8}) == {"a": 3}
    assert alerts.delta({"a": 9}, {"a": 2}) == {"a": 2}  # restarted process: counter reset
    assert alerts.counted_loss("fluentbit", {"dropped_records": 4, "retries_failed": 2}) == 4


def test_ts_ns():
    assert reconcile_es.ts_ns("1970-01-01T00:00:01.000000001Z") == 1_000_000_001
    assert reconcile_es.ts_ns("1970-01-01T01:00:00.5+01:00") == 500_000_000
    assert reconcile_es.ts_ns(None) is None


def test_to_arrival_fields():
    msg = build("abc", "journald", 4, 1)
    doc = {"message": msg, "@timestamp": "2026-11-14T14:07:21.820Z", "event": {"ingested": "2026-11-14T14:07:22Z"},
           "host": {"hostname": "lab-host"}, "log": {"syslog": {"appname": "logcanary"}}}
    a = reconcile_es.to_arrival("filebeat", doc, "abc")
    assert a["seq"] == 4 and a["check"] == "exact" and a["fields_ok"]
    doc["host"]["hostname"] = "6678d1e9a486"
    assert not reconcile_es.to_arrival("filebeat", doc, "abc")["fields_ok"]
    assert reconcile_es.to_arrival("filebeat", doc, "other") is None
    flat = {"message": msg, "@timestamp": "2026-11-14T14:07:21Z", "event.ingested": "2026-11-14T14:07:22Z",
            "_HOSTNAME": "lab-host", "SYSLOG_IDENTIFIER": "logcanary"}
    assert reconcile_es.to_arrival("fluentbit", flat, "abc")["fields_ok"]
