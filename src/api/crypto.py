"""Cross-platform credential protection helper without third-party dependencies.

On Windows: Uses Windows DPAPI (CryptProtectData / CryptUnprotectData via ctypes in crypt32.dll).
On Linux / Fallback: Uses PBKDF2-HMAC-SHA256 key derivation with Encrypt-then-MAC
(HMAC-SHA256 authenticated stream cipher, protected alongside 0600 file permissions).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import struct
import sys

PREFIX = "enc:"
V2_PREFIX = "v2:"
V2_ITERATIONS = 200_000


if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    class _DATA_BLOB(ctypes.Structure):
        _fields_ = [
            ("cbData", wintypes.DWORD),
            ("pbData", ctypes.POINTER(ctypes.c_byte)),
        ]

    _crypt32 = ctypes.windll.crypt32
    _kernel32 = ctypes.windll.kernel32

    _crypt32.CryptProtectData.argtypes = [
        ctypes.POINTER(_DATA_BLOB),
        wintypes.LPCWSTR,
        ctypes.POINTER(_DATA_BLOB),
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(_DATA_BLOB),
    ]
    _crypt32.CryptProtectData.restype = wintypes.BOOL

    _crypt32.CryptUnprotectData.argtypes = [
        ctypes.POINTER(_DATA_BLOB),
        ctypes.POINTER(wintypes.LPWSTR),
        ctypes.POINTER(_DATA_BLOB),
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(_DATA_BLOB),
    ]
    _crypt32.CryptUnprotectData.restype = wintypes.BOOL

    _kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    _kernel32.LocalFree.restype = ctypes.c_void_p

    def _win_encrypt(plaintext: str) -> str:
        data = plaintext.encode("utf-8")
        buf = ctypes.create_string_buffer(data)
        in_blob = _DATA_BLOB(
            len(data),
            ctypes.cast(buf, ctypes.POINTER(ctypes.c_byte)),
        )
        out_blob = _DATA_BLOB()
        # 1 = CRYPTPROTECT_UI_FORBIDDEN
        ret = _crypt32.CryptProtectData(
            ctypes.byref(in_blob),
            "trafficbox_secret",
            None,
            None,
            None,
            1,
            ctypes.byref(out_blob),
        )
        if not ret:
            raise OSError("CryptProtectData failed")
        try:
            raw = ctypes.string_at(out_blob.pbData, out_blob.cbData)
            return PREFIX + base64.b64encode(raw).decode("ascii")
        finally:
            _kernel32.LocalFree(out_blob.pbData)

    def _win_decrypt(b64_payload: str) -> str:
        raw = base64.b64decode(b64_payload)
        buf = ctypes.create_string_buffer(raw)
        in_blob = _DATA_BLOB(
            len(raw),
            ctypes.cast(buf, ctypes.POINTER(ctypes.c_byte)),
        )
        out_blob = _DATA_BLOB()
        # 1 = CRYPTPROTECT_UI_FORBIDDEN
        ret = _crypt32.CryptUnprotectData(
            ctypes.byref(in_blob),
            None,
            None,
            None,
            None,
            1,
            ctypes.byref(out_blob),
        )
        if not ret:
            raise OSError("CryptUnprotectData failed")
        try:
            raw_out = ctypes.string_at(out_blob.pbData, out_blob.cbData)
            return raw_out.decode("utf-8")
        finally:
            _kernel32.LocalFree(out_blob.pbData)


def _get_machine_user_salt() -> bytes:
    """Return platform and user specific salt bytes."""
    components: list[str] = [sys.platform, os.environ.get("USER", os.environ.get("USERNAME", "user"))]
    if hasattr(os, "getuid"):
        components.append(f"uid:{os.getuid()}")
    for p in ("/etc/machine-id", "/var/lib/dbus/machine-id"):
        if os.path.isfile(p):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    content = f.read().strip()
                if content:
                    components.append(content)
                    break
            except OSError:
                pass
    return hashlib.sha256(":".join(components).encode("utf-8")).digest()


def _pbkdf2_stream_cipher(data: bytes, key_bytes: bytes, salt: bytes) -> bytes:
    """Legacy v1 symmetric stream XOR cipher derived via PBKDF2-HMAC-SHA256."""
    derived = hashlib.pbkdf2_hmac("sha256", key_bytes, salt, 20000, len(data))
    return bytes(a ^ b for a, b in zip(data, derived))


def _hmac_ctr_keystream(enc_key: bytes, salt: bytes, length: int) -> bytes:
    """Generate a pseudorandom keystream via counter-mode HMAC-SHA256."""
    chunks: list[bytes] = []
    produced = 0
    ctr = 0
    while produced < length:
        block = hmac.new(enc_key, salt + struct.pack(">I", ctr), hashlib.sha256).digest()
        chunks.append(block)
        produced += len(block)
        ctr += 1
    return b"".join(chunks)[:length]


def _generic_encrypt(plaintext: str) -> str:
    """Encrypt plaintext using PBKDF2-HMAC-SHA256 + Encrypt-then-MAC (v2)."""
    salt = os.urandom(16)
    key_seed = _get_machine_user_salt()
    key_mat = hashlib.pbkdf2_hmac("sha256", key_seed, salt, V2_ITERATIONS, 64)
    enc_key, mac_key = key_mat[:32], key_mat[32:]

    data = plaintext.encode("utf-8")
    stream = _hmac_ctr_keystream(enc_key, salt, len(data))
    cipher_bytes = bytes(a ^ b for a, b in zip(data, stream))
    tag = hmac.new(mac_key, b"v2" + salt + cipher_bytes, hashlib.sha256).digest()
    payload = salt + tag + cipher_bytes
    return PREFIX + V2_PREFIX + base64.b64encode(payload).decode("ascii")


def _generic_decrypt(b64_payload: str) -> str:
    """Decrypt v2 (authenticated) or legacy v1 generic secret payloads."""
    if b64_payload.startswith(V2_PREFIX):
        raw = base64.b64decode(b64_payload[len(V2_PREFIX) :], validate=True)
        if len(raw) < 48:
            raise ValueError("Invalid encrypted v2 payload size")
        salt = raw[:16]
        tag = raw[16:48]
        cipher_bytes = raw[48:]
        key_seed = _get_machine_user_salt()
        key_mat = hashlib.pbkdf2_hmac("sha256", key_seed, salt, V2_ITERATIONS, 64)
        enc_key, mac_key = key_mat[:32], key_mat[32:]
        expected_tag = hmac.new(mac_key, b"v2" + salt + cipher_bytes, hashlib.sha256).digest()
        if not hmac.compare_digest(tag, expected_tag):
            raise ValueError("Authentication failed")
        stream = _hmac_ctr_keystream(enc_key, salt, len(cipher_bytes))
        decrypted = bytes(a ^ b for a, b in zip(cipher_bytes, stream))
        return decrypted.decode("utf-8")

    raw = base64.b64decode(b64_payload)
    if len(raw) < 16:
        raise ValueError("Invalid encrypted payload size")
    salt = raw[:16]
    cipher_bytes = raw[16:]
    key_seed = _get_machine_user_salt()
    decrypted = _pbkdf2_stream_cipher(cipher_bytes, key_seed, salt)
    return decrypted.decode("utf-8")


def encrypt_secret(plaintext: str) -> str:
    """Encrypt a secret string into a safe, portable base64 representation prefixed with enc:."""
    if not plaintext:
        return ""
    if plaintext.startswith(PREFIX):
        return plaintext

    if sys.platform == "win32":
        try:
            return _win_encrypt(plaintext)
        except Exception:
            return _generic_encrypt(plaintext)
    return _generic_encrypt(plaintext)


def decrypt_secret(cipher_text: str) -> str:
    """Decrypt a previously encrypted secret string. Returns plaintext as-is if unencrypted."""
    if not cipher_text:
        return ""
    if not cipher_text.startswith(PREFIX):
        # Legacy unencrypted plaintext fallback
        return cipher_text

    payload = cipher_text[len(PREFIX) :]
    if sys.platform == "win32":
        try:
            return _win_decrypt(payload)
        except Exception:
            try:
                return _generic_decrypt(payload)
            except Exception:
                return ""
    try:
        return _generic_decrypt(payload)
    except Exception:
        return ""
