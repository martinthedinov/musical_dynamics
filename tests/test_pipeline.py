"""Format-independent pipeline: framing, packing, fountain code, AES-GCM crypto, PRNG."""
import os
import numpy as np
import pytest

from stego import pipeline, crypto
from stego.bitio import mulberry32, perm, bytes_to_bits, bits_to_bytes, crc16
from stego.fountain import Fountain, blocks_of, decode as lt_decode


# ---------- PRNG: byte-identical to the JS app's mulberry32 + Fisher-Yates ----------
def test_mulberry32_known_vector():
    """The first six draws from seed 0x6d6432 match the JS reference values."""
    r = mulberry32(0x6d6432)
    got = [round(r(), 12) for _ in range(6)]
    expected = [0.842230277602, 0.637956989231, 0.120746918255,
                0.292125375941, 0.948608695064, 0.54758424079]
    assert got == expected, "PRNG drifted from the JS reference — cross-impl interop is broken"

def test_permutation_is_a_permutation():
    p = perm(64, 0xCAFE)
    assert sorted(p.tolist()) == list(range(64))
    assert len(set(p.tolist())) == 64

def test_perm_deterministic():
    assert (perm(32, 1) == perm(32, 1)).all()
    assert (perm(32, 1) != perm(32, 2)).any()


# ---------- bits<->bytes ----------
def test_bit_roundtrip_random():
    rng = np.random.RandomState(0)
    for n in (1, 7, 8, 23, 1024):
        data = rng.bytes(n)
        bits = bytes_to_bits(data)
        assert bits.size == n * 8
        assert bits_to_bytes(bits) == data


# ---------- CRC-16 sanity ----------
def test_crc16_changes_on_bit_flip():
    for n in (8, 64, 256):
        data = os.urandom(n)
        c1 = crc16(data)
        for i in (0, n // 2, n - 1):
            flipped = bytes(data[:i] + bytes([data[i] ^ 1]) + data[i+1:])
            assert crc16(flipped) != c1, "CRC-16 failed to detect a single-bit flip"


# ---------- fountain code: encode -> erase symbols -> decode ----------
@pytest.mark.parametrize("K,B,redundancy,loss_frac", [
    (10,  16, 4.0, 0.30),
    (32,  64, 4.0, 0.50),
    (95,  64, 3.0, 0.30),
    (128, 32, 2.0, 0.10),
])
def test_fountain_survives_random_symbol_erasures(K, B, redundancy, loss_frac):
    """LT decoder recovers all K blocks from any K' ~ K surviving symbols at the chosen loss
       fraction. Redundancy is tuned per case — LT's recovery probability rises sharply with
       redundancy and tapers off near the loss fraction's threshold."""
    rng = np.random.RandomState(K)
    data = rng.bytes(K * B)
    blocks, _ = blocks_of(data, B)
    fnt = Fountain(K, B, seed=0xABCD)
    n_sym = int(K * redundancy)
    symbols = {i: fnt.encode_symbol(blocks, i).tobytes() for i in range(n_sym)}
    keep = rng.choice(n_sym, size=int(n_sym * (1 - loss_frac)), replace=False)
    surviving = {i: symbols[i] for i in keep}
    recovered = lt_decode(surviving, fnt)
    assert recovered is not None, f"LT failed at K={K} loss={loss_frac:.0%} redundancy={redundancy}x"
    assert recovered == data

def test_fountain_refuses_below_threshold():
    """Way too few symbols -> returns None (caller should refuse, never silent-wrong)."""
    K, B = 64, 32
    data = os.urandom(K * B)
    blocks, _ = blocks_of(data, B)
    fnt = Fountain(K, B, seed=1)
    # only K/4 symbols -> can't possibly decode
    syms = {i: fnt.encode_symbol(blocks, i).tobytes() for i in range(K // 4)}
    assert lt_decode(syms, fnt) is None


# ---------- pack/unpack: zlib + framing + CRC ----------
def test_pack_unpack_roundtrip(alice_text):
    coded, flags = pipeline.pack(alice_text, "alice.txt")
    assert flags & pipeline.FLAG_ZLIB, "text should compress (and the flag should be set)"
    name, got = pipeline.unpack(coded, flags)
    assert name == "alice.txt"
    assert got == alice_text

def test_pack_unpack_random_doesnt_compress(random_payload):
    """Incompressible payload: pack should *not* set the zlib flag."""
    coded, flags = pipeline.pack(random_payload, "blob.bin")
    assert not (flags & pipeline.FLAG_ZLIB)
    name, got = pipeline.unpack(coded, flags)
    assert got == random_payload

def test_unpack_detects_corruption(alice_text):
    coded, flags = pipeline.pack(alice_text, "alice.txt")
    bad = bytearray(coded); bad[len(bad)//2] ^= 0xFF
    with pytest.raises(pipeline.PipelineError):
        pipeline.unpack(bytes(bad), flags)


# ---------- AES-GCM crypto: round-trip + wrong password ----------
def test_crypto_roundtrip(alice_text):
    blob = crypto.encrypt(alice_text, "correct horse")
    assert crypto.is_encrypted(blob)
    assert crypto.decrypt(blob, "correct horse") == alice_text

def test_crypto_wrong_password_refuses(alice_text):
    blob = crypto.encrypt(alice_text, "right")
    with pytest.raises(crypto.CryptoError):
        crypto.decrypt(blob, "wrong")

def test_crypto_no_password_is_identity(alice_text):
    assert crypto.encrypt(alice_text, None) is alice_text
    assert crypto.decrypt(alice_text, None) is alice_text
