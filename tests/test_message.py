import zlib

from hypothesis import given
from hypothesis import strategies as st

from logcanary import message


def test_plain_roundtrip_is_exact():
    m = message.build("ab12", "syslog", 7, 123, "plain", 256)
    assert message.check(m) == "exact"
    h = message.parse_head(m)
    assert (h["run"], h["src"], h["seq"], h["ts"], h["kind"]) == ("ab12", "syslog", 7, 123, "plain")


def test_size_is_close_to_target():
    for size in (256, 1024, 8192, 65536):
        assert abs(len(message.build("ab", "journald", 1, 1, "plain", size).encode()) - size) <= 2


def test_every_kind_is_exact_untouched():
    for kind in message.KINDS:
        assert message.check(message.build("ff", "syslog", 3, 9, kind, 600)) == "exact"


def test_rsyslog_escaping_is_recoverable():
    m = message.build("ab", "syslog", 1, 1, "multiline", 400)
    assert "\n" in m
    escaped = m.replace("\n", "#012").replace("\t", "#011")
    assert message.check(escaped) == "recoverable"


def test_truncation_detected():
    m = message.build("ab", "syslog", 1, 1, "plain", 9000)
    assert message.check(m[:8096]) == "truncated"
    assert message.parse_head(m[:8096])["seq"] == 1


def test_damage_detected():
    m = message.build("ab", "syslog", 1, 1, "unicode", 300)
    assert message.check(m.replace("日本語", "???")) == "damaged"


def test_syslog_prefix_is_ignored():
    m = message.build("ab", "syslog", 5, 1)
    line = "2026-11-14T14:07:21.820902+00:00 lab-host logcanary[353]: " + m
    assert message.check(line) == "exact"


def test_unparsed():
    assert message.check("hello world") == "unparsed"


@given(st.integers(0, 10**6), st.sampled_from(message.KINDS), st.integers(60, 3000))
def test_property_exact_and_crc_covers_body(seq, kind, size):
    m = message.build("c0ffee", "journald", seq, 42, kind, size)
    assert message.check(m) == "exact"
    body, crc = m.rsplit(" crc=", 1)
    assert zlib.crc32(body.encode()) == int(crc, 16)
