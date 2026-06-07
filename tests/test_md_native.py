"""MD-native compositional stego: hide data in the variation/voicing bits the decoder ignores.

The headline guarantee is that the produced music still decodes to the *exact same opcode
sequence and program output* as the unmodified realization — there is no audio tampering at
all, just a different (but equally valid) arrangement.
"""
import pytest
import numpy as np

import mc_codec as mc
from stego import md_native
from stego.crypto import CryptoError


# ---------- per-opcode bit capacity ----------
def test_bits_per_opcode_table_sane():
    """Each of the 21 opcodes has a non-negative bit budget and at least one carries data."""
    total = 0
    for op in mc.QFAMILY:
        b = md_native.bits_per_opcode(op)
        assert b >= 0
        total += b
    assert total > 0, "no opcode contributed any variation bits — capacity engine is broken"


# ---------- a payload-driven performance still decodes to the same program ----------
@pytest.mark.parametrize("name,src", [
    ("fibonacci", mc.DEMOS["fibonacci"]),
    ("primes",    mc.DEMOS["primes"]),
    ("fizzwords", mc.DEMOS["fizzwords"]),
])
def test_performance_decodes_to_same_program(name, src):
    """Embed arbitrary bits as variation; the music must still decode to the original opcodes."""
    code, _ = mc.compile_python(src)
    trace = [{"op": op, "arg": arg, "iter": 0, "val": None} for op, arg in code]
    cap = md_native.capacity_bits(trace)
    bits = np.random.RandomState(7).randint(0, 2, size=cap).astype(np.uint8)
    notes, used = md_native.realize_with_bits(trace, bits)
    assert used == cap
    decoded = mc.decode_notes(notes)
    assert decoded == code, f"{name}: variation drove decode off the program — that violates the invariance guarantee"
    assert [str(x) for x in mc.run(decoded)[0]] == mc.pyrun(src)


# ---------- bits round-trip through music ----------
@pytest.mark.parametrize("name,src", [
    ("primes",    mc.DEMOS["primes"]),
    ("fizzwords", mc.DEMOS["fizzwords"]),
])
def test_variation_bits_roundtrip(name, src):
    """The exact bit pattern fed into realize_with_bits comes back out of extract_bits_from_notes."""
    code, _ = mc.compile_python(src)
    trace = [{"op": op, "arg": arg, "iter": 0, "val": None} for op, arg in code]
    cap = md_native.capacity_bits(trace)
    bits = np.random.RandomState(42).randint(0, 2, size=cap).astype(np.uint8)
    notes, _ = md_native.realize_with_bits(trace, bits)
    got = md_native.extract_bits_from_notes(notes)
    assert got.size >= cap
    assert (got[:cap] == bits).all(), "variation bit stream mismatched after music round-trip"


# A long synthesized program — gives enough native capacity for a few dozen payload bytes,
# enough headroom for AES-GCM's ~48-byte overhead, and is still a real Python program.
def _long_program():
    src = "\n".join(f"v{i} = {i}\nprint(v{i})" for i in range(80))   # ~320 opcodes -> ~800 bits cap
    return mc.compile_python(src)[0], src


# ---------- full file embed/extract through the native channel ----------
def test_md_native_file_roundtrip(preamble_text):
    """Hide a small payload in the variation channel of a real program; recover bit-exact AND
       verify the music still decodes to the exact original program."""
    code = mc.compile_python(mc.DEMOS["fizzwords"])[0]    # 64 opcodes, 181 bits capacity
    payload = preamble_text[:8]                            # 8 bytes -> 12-byte frame, 96 bits at rep=1
    notes, info = md_native.embed_payload(code, payload, repetition=1)
    # the headline invariance guarantee: decoded opcodes are EXACTLY the input program
    assert mc.decode_notes(notes) == code
    assert [str(x) for x in mc.run(mc.decode_notes(notes))[0]] == mc.pyrun(mc.DEMOS["fizzwords"])
    got = md_native.extract_payload(notes, repetition=1)
    assert got == payload, "MD-native channel lost bytes"

def test_md_native_with_redundancy(preamble_text):
    """A longer program has enough capacity for repetition coding."""
    code, src = _long_program()
    payload = preamble_text[:32]                          # 36-byte frame * 3x rep = 864 bits, fits in ~960
    notes, info = md_native.embed_payload(code, payload, repetition=3)
    assert mc.decode_notes(notes) == code
    got = md_native.extract_payload(notes, repetition=3)
    assert got == payload
    assert info["repetition"] == 3 and info["slack_bits"] >= 0

def test_md_native_with_password(preamble_text):
    """AES-GCM adds ~48 bytes overhead — needs a longer program."""
    code, _ = _long_program()
    payload = preamble_text[:8]
    notes, _ = md_native.embed_payload(code, payload, password="hunter2", repetition=1)
    assert mc.decode_notes(notes) == code
    got = md_native.extract_payload(notes, password="hunter2", repetition=1)
    assert got == payload
    with pytest.raises(CryptoError):
        md_native.extract_payload(notes, password="wrong", repetition=1)

def test_md_native_too_small_refuses(preamble_text):
    """Program with too little capacity raises rather than corrupting."""
    code, _ = mc.compile_python(mc.DEMOS["hello"])
    with pytest.raises(md_native.NativeError):
        md_native.embed_payload(code, preamble_text[:50], repetition=3)

def test_md_native_capacity_reporting():
    """capacity_bits agrees with what realize_with_bits actually consumes."""
    code, _ = mc.compile_python(mc.DEMOS["primes"])
    trace = [{"op": op, "arg": arg, "iter": 0, "val": None} for op, arg in code]
    cap = md_native.capacity_bits(trace)
    bits = np.zeros(cap, dtype=np.uint8)
    _, used = md_native.realize_with_bits(trace, bits)
    assert used == cap
