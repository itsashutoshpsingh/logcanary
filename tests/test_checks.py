from logcanary.conditions import nominal_size
from logcanary.runner import checks_by


def test_checks_by_size_counts_first_copy_and_lost():
    ledger = [{"src": "syslog", "seq": str(i), "size_bytes": str(s), "kind": "plain"}
              for i, s in enumerate((1030, 65530, 65540))]
    arrivals = [
        {"shipper": "filebeat", "src": "syslog", "seq": "0", "check": "exact", "fields_ok": "True"},
        {"shipper": "filebeat", "src": "syslog", "seq": "0", "check": "damaged", "fields_ok": "True"},  # duplicate
        {"shipper": "filebeat", "src": "syslog", "seq": "1", "check": "truncated", "fields_ok": "True"},
        {"shipper": "vector", "src": "syslog", "seq": "2", "check": "exact", "fields_ok": "True"},  # other shipper
    ]
    assert nominal_size(8195) == 8200
    assert checks_by(ledger, arrivals, "filebeat", "syslog", "size") == {
        "1024": {"intact": 1}, "65536": {"truncated": 1, "lost": 1}}


def test_throttle_windows_close_on_stop_or_node_stop():
    from logcanary.report import es_throttled, throttle_windows

    def ev(t, msg, logger="engine"):
        return {"@timestamp": f"2026-11-14T14:00:{t:02d}Z", "message": msg, "log.logger": logger}

    w = throttle_windows([ev(1, "now throttling indexing: a"), ev(2, "now throttling indexing: b"),
                          ev(3, "stop throttling indexing: a"), ev(5, "stop throttling indexing: b"),
                          ev(10, "now throttling indexing: c"), ev(12, "stopping ...", "o.e.node.Node"),
                          ev(20, "now throttling indexing: d")])
    s = 1_794_664_800 * 10**9  # 2026-11-14T14:00:00Z
    assert w == [(s + 10**9, s + 5 * 10**9), (s + 10 * 10**9, s + 12 * 10**9), (s + 20 * 10**9, None)]
    meta = {"t_start_ns": s + 6 * 10**9, "t_writer_done_ns": s + 8 * 10**9, "settle": {"waited_s": 1.5}}
    assert not es_throttled(meta, w)
    meta["settle"]["waited_s"] = 2.5
    assert es_throttled(meta, w)


def test_throttle_window_ends_at_last_line_when_node_died():
    from logcanary.report import throttle_windows

    def ev(t, msg, logger="engine"):
        return {"@timestamp": f"2026-11-14T14:00:{t:02d}Z", "message": msg, "log.logger": logger}

    s = 1_794_664_800 * 10**9
    w = throttle_windows([ev(1, "now throttling indexing: a"), ev(4, "insufficient disk space"),
                          ev(9, "started {node}", "o.e.node.Node")])
    assert w == [(s + 10**9, s + 4 * 10**9)]
