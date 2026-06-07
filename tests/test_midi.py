"""MIDI carrier: hide bits in the low bits of note-on velocities."""
import pytest

pytest.importorskip("mido")
import mido

from stego.carriers import embed_file, extract_file


def test_midi_roundtrip(long_mid, sonnet_text, tmp_path):
    pl = tmp_path / "sonnet.txt"; pl.write_bytes(sonnet_text[:120])
    out = tmp_path / "stego.mid"
    info = embed_file(long_mid, str(out), str(pl), n_lsb=2, block_size=16, rs_nsym=6,
                      redundancy=None)
    assert info["payload_bytes"] == 120
    rec, _ = extract_file(str(out), str(tmp_path))
    assert open(rec, "rb").read() == sonnet_text[:120]


def test_midi_velocity_delta_bounded(long_mid, alice_text, tmp_path):
    """At n_lsb=2 every velocity changes by at most 3 (mask = low 2 bits)."""
    pl = tmp_path / "alice.txt"; pl.write_bytes(alice_text[:80])
    out = tmp_path / "stego.mid"
    embed_file(long_mid, str(out), str(pl), n_lsb=2, block_size=16, rs_nsym=6, redundancy=None)
    a = mido.MidiFile(long_mid); b = mido.MidiFile(str(out))
    max_delta = 0
    for t1, t2 in zip(a.tracks, b.tracks):
        for m1, m2 in zip(t1, t2):
            if m1.type == "note_on" and m1.velocity > 0:
                max_delta = max(max_delta, abs(m1.velocity - m2.velocity))
    assert max_delta <= 3, f"velocity delta {max_delta} > 3 — wrote bits beyond the LSB mask"


def test_midi_event_order_and_count_preserved(long_mid, alice_text, tmp_path):
    """Stego must not change event order, count, type, pitch, or timing — only velocity LSBs."""
    pl = tmp_path / "alice.txt"; pl.write_bytes(alice_text[:60])
    out = tmp_path / "stego.mid"
    embed_file(long_mid, str(out), str(pl), n_lsb=2, block_size=16, rs_nsym=6, redundancy=None)
    a = mido.MidiFile(long_mid); b = mido.MidiFile(str(out))
    assert len(a.tracks) == len(b.tracks)
    for t1, t2 in zip(a.tracks, b.tracks):
        assert len(t1) == len(t2)
        for m1, m2 in zip(t1, t2):
            assert m1.type == m2.type
            assert getattr(m1, "time", 0) == getattr(m2, "time", 0)
            for attr in ("note", "channel", "control"):
                if hasattr(m1, attr):
                    assert getattr(m1, attr) == getattr(m2, attr)


def test_midi_with_password(long_mid, preamble_text, tmp_path):
    pl = tmp_path / "pre.txt"; pl.write_bytes(preamble_text[:60])
    out = tmp_path / "enc.mid"
    embed_file(long_mid, str(out), str(pl), n_lsb=2, block_size=16, rs_nsym=6, redundancy=None,
               password="hunter2")
    rec, _ = extract_file(str(out), str(tmp_path), password="hunter2")
    assert open(rec, "rb").read() == preamble_text[:60]
