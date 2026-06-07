"""Optional AES-256-GCM with a passphrase (scrypt KDF).

When a password is supplied the payload is encrypted+authenticated, which also *whitens*
the bits (uniform, near-random) — both private and harder to detect statistically. When no
password is given these are identity functions. Requires the `cryptography` package only
when a password is actually used.

Wire format:  magic(b"MDE1") | salt(16) | nonce(12) | ciphertext+tag
"""
import os

_EMAGIC = b"MDE1"
_SALT, _NONCE = 16, 12

class CryptoError(Exception): pass

def _aesgcm():
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
        return AESGCM, Scrypt
    except Exception as e:  # pragma: no cover
        raise CryptoError("AES-GCM needs the 'cryptography' package (pip install cryptography): %s" % e)

def _key(password, salt):
    AESGCM, Scrypt = _aesgcm()
    kdf = Scrypt(salt=salt, length=32, n=2**14, r=8, p=1)
    return AESGCM(kdf.derive(password.encode("utf-8")))

def encrypt(data, password):
    if not password:
        return data
    AESGCM, _ = _aesgcm()
    salt, nonce = os.urandom(_SALT), os.urandom(_NONCE)
    ct = _key(password, salt).encrypt(nonce, data, None)
    return _EMAGIC + salt + nonce + ct

def decrypt(blob, password):
    if not password:
        return blob
    if blob[:4] != _EMAGIC:
        raise CryptoError("payload is not encrypted (or wrong format) but a password was given")
    salt = blob[4:4 + _SALT]; nonce = blob[4 + _SALT:4 + _SALT + _NONCE]; ct = blob[4 + _SALT + _NONCE:]
    try:
        return _key(password, salt).decrypt(nonce, ct, None)
    except Exception as e:
        raise CryptoError("decryption failed (wrong password or corrupted payload): %s" % e)

def is_encrypted(blob):
    return blob[:4] == _EMAGIC
