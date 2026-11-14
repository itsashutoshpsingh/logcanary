import struct

from logcanary.writer import journal_payload


def test_journal_native_encoding():
    assert journal_payload({"MESSAGE": "hi", "P": "6"}) == b"MESSAGE=hi\nP=6\n"
    b = journal_payload({"MESSAGE": "a\nb"})
    assert b == b"MESSAGE\n" + struct.pack("<Q", 3) + b"a\nb\n"
