"""Song -> MD prototype: turn an arbitrary MIDI piece into the closest valid MD program.

We test two cases:
  1) MD-generated MIDI (a known program realized as music) should round-trip back to a
     fidelity-1.0 program with the same OUT count.
  2) An arbitrary non-MD chord progression should produce a balanced, valid program with a
     numeric fidelity score in [0,1].
"""
import os, tempfile, pytest

pytest.importorskip("mido")
import mido

import mc_codec as mc
from mc_song_to_md import song_to_md, chords_from_midi, repair_to_valid


def _write_md_hello(tmp_path):
    code, _ = mc.compile_python(mc.DEMOS["hello"])
    pst = [{"op": op, "arg": arg, "iter": 0, "val": None} for op, arg in code]
    notes, _ = mc.realize(pst, mode="pent_minor", key=3, octave=0, variation=2)
    p = str(tmp_path / "hello.mid"); mc.write_midi(notes, p)
    return p, code


def _write_chord_progression(tmp_path):
    """A non-MD song: I-V-vi-IV in C major, twice."""
    m = mido.MidiFile(); tr = mido.MidiTrack(); m.tracks.append(tr)
    tr.append(mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(120)))
    for ch in [[60,64,67],[55,59,62],[57,60,64],[53,57,60]] * 2:
        for n in ch: tr.append(mido.Message("note_on",  channel=0, note=n, velocity=80, time=0))
        for n in ch: tr.append(mido.Message("note_off", channel=0, note=n, velocity=0,
                                            time=240 if n == ch[0] else 0))
    p = str(tmp_path / "prog.mid"); m.save(p)
    return p


def test_md_generated_midi_roundtrips_at_full_fidelity(tmp_path):
    """A piece we ourselves realized from a known program should round-trip exactly: every
       chord matches a single QFAMILY member, fidelity = 1.0."""
    p, _ = _write_md_hello(tmp_path)
    md, opcodes, fidelity, n_events = song_to_md(p)
    assert fidelity == pytest.approx(1.0, abs=1e-6), f"expected 1.0, got {fidelity}"
    assert n_events > 0
    # ...and the recovered MD should compile (the round-trip music *was* a valid program)
    code, _ = mc.compile_md(md)
    assert len(code) > 0


def test_arbitrary_progression_yields_valid_balanced_program(tmp_path):
    """An arbitrary chord progression: the result must be a valid (balanced, no underflow)
       opcode stream — what the visual composer would call a "complete program". Fidelity in [0,1]."""
    p = _write_chord_progression(tmp_path)
    md, opcodes, fidelity, n = song_to_md(p)
    assert 0.0 <= fidelity <= 1.0
    # validity (mirror of repair_to_valid's invariant)
    from mc_song_to_md import _check
    _, ctrl, bad = _check(opcodes)
    assert bad is None, f"repair produced an invalid program: {bad}"
    assert ctrl == [], "all blocks should be closed"


def test_chord_clustering_filters_md_operand_channel(tmp_path):
    """When the MIDI uses MD's channel convention, chord clustering must skip operand/bass
       channels — otherwise the signature gets contaminated and fidelity drops."""
    p, _ = _write_md_hello(tmp_path)
    events = chords_from_midi(p)
    # the MD Hello World has 15 opcodes -> 15 chord events
    assert len(events) == 15
