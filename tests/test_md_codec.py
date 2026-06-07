"""Musical Dynamics codec: opcode IR, Python+MD compilers, decompilers, music round-trip."""
import pytest
import mc_codec as mc


# ---------- the bedrock guarantee ----------
@pytest.mark.parametrize("name,src", list(mc.DEMOS.items()))
def test_python_program_runs_match_real_python(name, src):
    """compile_python -> run produces the same printed output as real Python on the same source."""
    code, _ = mc.compile_python(src)
    out = [str(x) for x in mc.run(code)[0]]
    assert out == mc.pyrun(src)


@pytest.mark.parametrize("name,src", list(mc.DEMOS.items()))
def test_score_mode_music_decodes_to_one_program(name, src):
    """SCORE mode: any rendering of the static program decodes back to the exact opcodes."""
    code, _ = mc.compile_python(src)
    pst = [{"op": op, "arg": arg, "iter": 0, "val": None} for op, arg in code]
    for var in range(4):
        for mode in ("major", "pent_minor", "whole_tone"):
            for key in (0, 5, 11):
                notes, _ = mc.realize(pst, mode=mode, key=key, climb_step=var % 3,
                                       octave=var % 2, variation=var)
                assert mc.decode_notes(notes) == code, (
                    f"{name}: rendering (mode={mode}, key={key}, var={var}) did not decode back exactly")


@pytest.mark.parametrize("name,src", list(mc.DEMOS.items()))
def test_perf_mode_trace_recovered_exactly(name, src):
    """PERFORMANCE mode: the unrolled execution trace is recoverable from the notes."""
    code, _ = mc.compile_python(src)
    _, trace, _ = mc.run(code)
    traceops = [(s["op"], s["arg"]) for s in trace]
    for var in range(3):
        for mode in ("major", "pent_minor"):
            notes, _ = mc.realize(trace, mode=mode, key=(var * 2) % 12, variation=var)
            assert mc.decode_notes(notes) == traceops


@pytest.mark.parametrize("name,src", list(mc.DEMOS.items()))
def test_decompile_is_runnable_python(name, src):
    code, _ = mc.compile_python(src)
    src2 = mc.decompile(code)
    assert mc.pyrun(src2) == mc.pyrun(src), f"decompiled Python ran differently for {name}"


# ---------- MD language: round-trips and bridge to Python ----------
@pytest.mark.parametrize("name,src", list(mc.MD_DEMOS.items()))
def test_md_compiles_and_runs(name, src):
    code, _ = mc.compile_md(src)
    out = [str(x) for x in mc.run(code)[0]]
    # Compare against the Python decompiled form running under real Python
    ref = mc.pyrun(mc.decompile(code))
    assert out == ref

@pytest.mark.parametrize("name,src", list(mc.MD_DEMOS.items()))
def test_md_decompile_is_idempotent(name, src):
    """MD source -> opcodes -> MD source -> opcodes must yield the same opcodes."""
    code1, _ = mc.compile_md(src)
    src2 = mc.decompile_md(code1)
    code2, _ = mc.compile_md(src2)
    assert code1 == code2

@pytest.mark.parametrize("name,src", list(mc.DEMOS.items()))
def test_python_to_md_preserves_behavior(name, src):
    """python_to_md goes through the opcode IR -> the recovered MD runs to the same output."""
    md = mc.python_to_md(src)
    code, _ = mc.compile_md(md)
    out = [str(x) for x in mc.run(code)[0]]
    assert out == mc.pyrun(src)


# ---------- operand encoding: lossless over the whole legal range, incl. full Unicode ----------
@pytest.mark.parametrize("v", [0, 1, 127, 1727, 2000, 20013, 127925, 0x10FFFF, mc.OPERAND_MAX])
def test_operand_lossless(v):
    assert mc.dec_operand(mc.enc_operand(v)) == v

@pytest.mark.parametrize("v", [-1, mc.OPERAND_MAX + 1, mc.OPERAND_MAX * 2])
def test_operand_rejects_out_of_range(v):
    with pytest.raises(ValueError):
        mc.enc_operand(v)

def test_unicode_program_music_roundtrips():
    """Emoji and CJK should compile, run, and survive a music round-trip."""
    src = 'print("♪ 中 🎵");'
    code, _ = mc.compile_md(src)
    pst = [{"op": op, "arg": arg, "iter": 0, "val": None} for op, arg in code]
    notes, _ = mc.realize(pst, variation=1)
    assert mc.decode_notes(notes) == code


# ---------- chord/opcode bijection ----------
def test_chord_qualities_all_disjoint():
    assert len(mc.QREV) == 27, "27 distinct chord signatures expected"
    assert len(mc.QFAMILY) == 21, "21 opcodes expected"
    sigs = set()
    for fam in mc.QFAMILY.values():
        for q in fam:
            sig = tuple(sorted(set(x % 12 for x in q)))
            assert sig not in sigs, f"collision at signature {sig}"
            sigs.add(sig)
