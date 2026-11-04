"""Cross-platform encryption helper for securing stored credentials without third-party dependencies.

On Windows: Uses Windows DPAPI (CryptProtectData / CryptUnprotectData via ctypes in crypt32.dll).
On Linux: Uses openssl AES-256-CBC with machine/user key derivation or standard PBKDF2 stream cipher fallback.
"""

from __future__ import annotations

import base64
import hashlib
import os
import sys

PREFIX = "enc:"


if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    class _DATA_BLOB(ctypes.Structure):
        _fields_ = [
            ("cbData", wintypes.DWORD),
            ("pbData", ctypes.POINTER(ctypes.c_byte)),
        ]

    def _win_encrypt(plaintext: str) -> str:
        data = plaintext.encode("utf-8")
        in_blob = _DATA_BLOB(
            len(data),
            ctypes.cast(ctypes.create_string_buffer(data), ctypes.POINTER(ctypes.c_byte)),
        )
        out_blob = _DATA_BLOB()
        # 1 = CRYPTPROTECT_UI_FORBIDDEN
        ret = ctypes.windll.crypt32.CryptProtectData(
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
            ctypes.windll.kernel32.LocalFree(out_blob.pbData)

    def _win_decrypt(b64_payload: str) -> str:
        raw = base64.b64decode(b64_payload)
        in_blob = _DATA_BLOB(
            len(raw),
            ctypes.cast(ctypes.create_string_buffer(raw), ctypes.POINTER(ctypes.c_byte)),
        )
        out_blob = _DATA_BLOB()
        # 1 = CRYPTPROTECT_UI_FORBIDDEN
        ret = ctypes.windll.crypt32.CryptUnprotectData(
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
            ctypes.windll.kernel32.LocalFree(out_blob.pbData)


def _get_machine_user_salt() -> bytes:
    """Return platform and user specific salt bytes."""
    components: list[str] = [sys.platform, os.environ.get("USER", os.environ.get("USERNAME", "user"))]
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
    """Symmetric stream XOR cipher derived via PBKDF2-HMAC-SHA256."""
    derived = hashlib.pbkdf2_hmac("sha256", key_bytes, salt, 20000, len(data))
    return bytes(a ^ b for a, b in zip(data, derived))


def _generic_encrypt(plaintext: str) -> str:
    salt = os.urandom(16)
    key_seed = _get_machine_user_salt()
    data = plaintext.encode("utf-8")
    cipher_bytes = _pbkdf2_stream_cipher(data, key_seed, salt)
    payload = salt + cipher_bytes
    return PREFIX + base64.b64encode(payload).decode("ascii")


def _generic_decrypt(b64_payload: str) -> str:
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
            return _generic_decrypt(payload)
    return _generic_decrypt(payload)
