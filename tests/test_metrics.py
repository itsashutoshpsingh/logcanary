from logcanary import metrics

S = 10**9


def ledger(n, t0=1_000 * S, step=S // 10):
    return [{"seq": i, "ts_wall_ns": t0 + i * step, "ts_host_ns": t0 + i * step, "kind": "plain", "send_err": ""}
            for i in range(n)]


def arr(seq, t_true, lat_s=1.0, skew_s=0.0, check="exact", ok=True):
    return {"seq": seq, "check": check, "ts_event_ns": t_true + int(skew_s * S),
            "ingested_ns": t_true + int(lat_s * S), "fields_ok": ok}


def test_no_loss():
    led = ledger(100)
    m = metrics.compute(led, [arr(r["seq"], r["ts_wall_ns"]) for r in led])
    assert m["loss_pct"] == 0 and m["duplicates"] == 0 and m["intact_pct"] == 100
    assert m["lat_p50_ms"] == 1000.0 and m["blind_pct"] == 0


def test_loss_duplicates_and_ranges():
    led = ledger(100)
    a = [arr(r["seq"], r["ts_wall_ns"]) for r in led if not 10 <= r["seq"] < 20]
    a += [arr(5, led[5]["ts_wall_ns"], lat_s=3)]  # a duplicate, arriving later
    m = metrics.compute(led, a)
    assert m["lost"] == 10 and m["loss_pct"] == 10.0
    assert m["duplicates"] == 1
    assert m["missing_ranges"] == [(10, 19)]
    assert m["lat_max_ms"] == 1000.0  # latency uses the first copy
    assert m["gap_rule_fires"] and m["gap_rule_missing"] == 10


def test_tail_loss_is_invisible_to_gap_rule():
    led = ledger(100)
    m = metrics.compute(led, [arr(r["seq"], r["ts_wall_ns"]) for r in led if r["seq"] < 80])
    assert m["lost"] == 20 and not m["gap_rule_fires"]


def test_unknown_seq_ignored():
    led = ledger(3)
    m = metrics.compute(led, [arr(99, 0)])
    assert m["unknown_seq_docs"] == 1 and m["arrived"] == 0 and m["loss_pct"] == 100.0


def test_fields_intact_needs_exact_message():
    led = ledger(4)
    a = [arr(0, led[0]["ts_wall_ns"]), arr(1, led[1]["ts_wall_ns"], check="recoverable"),
         arr(2, led[2]["ts_wall_ns"], ok=False), arr(3, led[3]["ts_wall_ns"], check="truncated")]
    m = metrics.compute(led, a)
    assert m["intact_pct"] == 25.0 and m["exact_pct"] == 50.0 and m["truncated"] == 1


def test_rule_probability():
    p = metrics.rule_seen_probability
    assert p(0, 1 * S) == 1.0  # 1 s delay: window is 5 m 59 s, always seen
    assert p(0, 60 * S) == 1.0  # exactly 1 minute late: window is still 5 m
    assert abs(p(0, 210 * S) - 0.5) < 1e-9  # 3.5 m late: window 2.5 m of a 5 m interval
    assert p(0, 400 * S) == 0.0  # later than the 6 m lookback: never
    assert p(-600 * S, 1 * S) == 0.0  # event stamped 10 min in the past
    assert p(7200 * S, 1 * S) == 1.0  # future dated: seen once the clock reaches it


def test_clock_skew_and_blindness():
    led = ledger(10)
    a = [arr(r["seq"], r["ts_wall_ns"], skew_s=-600) for r in led]
    m = metrics.compute(led, a)
    assert m["skew_p50_ms"] == -600_000.0 and m["blind_pct"] == 100.0 and m["loss_pct"] == 0


def test_percentile_and_ci():
    assert metrics.percentile([1, 2, 3, 4], 50) == 2.5
    assert metrics.percentile([], 50) is None
    m, lo, hi = metrics.mean_ci([1.0, 2.0, 3.0])
    assert m == 2.0 and abs(hi - 2.0 - 4.303 / 3**0.5) < 1e-9 and lo < m
    assert metrics.mean_ci([5.0]) == (5.0, None, None)
