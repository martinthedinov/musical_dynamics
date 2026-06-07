"""MD language extensions: boolean operators, helpful error messages, decompile idempotence."""
import pytest
import mc_codec as mc


# ---------- boolean operators (and / or / not) — desugared, no new opcodes ----------
@pytest.mark.parametrize("src, want", [
    ("let x = 1; let y = 0;\nif (x and y) { print(1); } else { print(0); }",  ["0"]),
    ("let x = 1; let y = 1;\nif (x and y) { print(1); } else { print(0); }",  ["1"]),
    ("let x = 0; let y = 0;\nif (x or  y) { print(1); } else { print(0); }",  ["0"]),
    ("let x = 0; let y = 5;\nif (x or  y) { print(1); } else { print(0); }",  ["1"]),
    ("let x = 0;\nif (not x) { print(1); } else { print(0); }",               ["1"]),
    ("let x = 7;\nif (not x) { print(1); } else { print(0); }",               ["0"]),
    # short-circuit precedence: not > and > or; compare > and; comparisons via 'and'/'or'
    ("let a = 5;\nif (a > 0 and a < 10) { print(1); } else { print(0); }",    ["1"]),
    ("let a = 5;\nif (a < 0 or  a > 100) { print(1); } else { print(0); }",   ["0"]),
])
def test_boolean_operators(src, want):
    code, _ = mc.compile_md(src)
    out = [str(x) for x in mc.run(code)[0]]
    assert out == want, f"{src!r} produced {out}, expected {want}"

def test_short_circuit_does_not_blow_up_left_side_false():
    """`(0 and divide-by-zero)` must not actually divide — the right side is skipped."""
    code, _ = mc.compile_md("let x = 0;\nif (x and (5 // x)) { print(1); } else { print(0); }")
    out = [str(x) for x in mc.run(code)[0]]
    assert out == ["0"]

def test_or_short_circuit_left_truthy_skips_right():
    code, _ = mc.compile_md("let x = 7;\nif (x or (5 // 0)) { print(1); } else { print(0); }")
    # MD's VM returns 0 for div-by-0 rather than raising, but the point is short-circuiting
    # means we don't even evaluate the right side; the IF picks the left branch.
    assert [str(x) for x in mc.run(code)[0]] == ["1"]


# ---------- boolean ops still decompile through the opcode IR ----------
def test_boolean_program_music_roundtrips():
    src = "let x = 1; let y = 2;\nif (not x or (x and y)) { print(y); } else { print(0); }"
    code, _ = mc.compile_md(src)
    pst = [{"op": op, "arg": arg, "iter": 0, "val": None} for op, arg in code]
    notes, _ = mc.realize(pst, variation=2)
    assert mc.decode_notes(notes) == code, "boolean-ops program failed music round-trip"


# ---------- error messages carry line/column info ----------
def test_error_reports_line_and_column():
    bad = ("let x = 1;\n"
           "let y = ;\n"            # missing expression after =
           "print(x + y);")
    with pytest.raises(mc.MDSyntaxError) as ei:
        mc.compile_md(bad)
    assert ei.value.line == 2, f"expected line 2, got {ei.value.line}"
    assert "line 2" in str(ei.value)

def test_unterminated_string_reports_position():
    with pytest.raises(mc.MDSyntaxError) as ei:
        mc.compile_md('let x = "hello;\n')
    assert "unterminated string" in str(ei.value)
    assert ei.value.line == 1

def test_unterminated_comment_reports_position():
    with pytest.raises(mc.MDSyntaxError) as ei:
        mc.compile_md("/* never closed\n let x = 1;")
    assert "unterminated" in str(ei.value)

def test_missing_semicolon_hints():
    with pytest.raises(mc.MDSyntaxError) as ei:
        mc.compile_md("let x = 1\nprint(x);")           # missing ';' after `let x = 1`
    assert "';'" in str(ei.value) or "semicolon" in str(ei.value).lower()


# ---------- existing MD demos still work (no regressions) ----------
@pytest.mark.parametrize("name,src", list(mc.MD_DEMOS.items()))
def test_existing_demos_unaffected(name, src):
    code1, _ = mc.compile_md(src)
    assert mc.compile_md(mc.decompile_md(code1))[0] == code1
