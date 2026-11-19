"""Unit tests for api/crypto.py."""

from __future__ import annotations

import base64
import os
import unittest

from src.api.crypto import (
    _generic_decrypt,
    _generic_encrypt,
    _get_machine_user_salt,
    _pbkdf2_stream_cipher,
    decrypt_secret,
    encrypt_secret,
)


class TestCrypto(unittest.TestCase):
    """Test secret encryption, decryption, and backward compatibility."""

    def test_empty_string(self) -> None:
        """Verify empty strings return empty without error."""
        self.assertEqual(encrypt_secret(""), "")
        self.assertEqual(decrypt_secret(""), "")

    def test_roundtrip(self) -> None:
        """Verify encrypting then decrypting returns original secret."""
        password = "my_super_secret_fritz_password_!@#$123"
        encrypted = encrypt_secret(password)
        self.assertTrue(encrypted.startswith("enc:"))
        self.assertNotEqual(encrypted, password)

        decrypted = decrypt_secret(encrypted)
        self.assertEqual(decrypted, password)

    def test_idempotent_encrypt(self) -> None:
        """Encrypting an already encrypted string should return it unchanged."""
        encrypted = "enc:AQAAANCMnd8BFdERjHoAwE"
        self.assertEqual(encrypt_secret(encrypted), encrypted)

    def test_legacy_plaintext_fallback(self) -> None:
        """Decrypting unencrypted plaintext should return the plaintext unmodified."""
        legacy_pwd = "plain_unencrypted_password"
        self.assertEqual(decrypt_secret(legacy_pwd), legacy_pwd)

    def test_generic_cipher_roundtrip(self) -> None:
        """Verify platform-independent PBKDF2-HMAC v2 authenticated cipher works reliably."""
        secret = "cross_platform_linux_test_pwd_99"
        enc = _generic_encrypt(secret)
        self.assertTrue(enc.startswith("enc:v2:"))
        dec = _generic_decrypt(enc[4:])
        self.assertEqual(dec, secret)

    def test_v2_tampered_ciphertext_rejected(self) -> None:
        """Verify HMAC-SHA256 authentication rejects tampered v2 ciphertexts."""
        enc = _generic_encrypt("secret_mac_check")
        raw = bytearray(base64.b64decode(enc[len("enc:v2:") :]))
        raw[-1] ^= 0xFF
        tampered = "enc:v2:" + base64.b64encode(bytes(raw)).decode("ascii")
        with self.assertRaises(ValueError):
            _generic_decrypt(tampered[4:])
        self.assertEqual(decrypt_secret(tampered), "")

    def test_legacy_v1_decrypt_compat(self) -> None:
        """Verify legacy v1 PBKDF2 payloads without v2: prefix remain decryptable."""
        salt = os.urandom(16)
        key_seed = _get_machine_user_salt()
        cipher_bytes = _pbkdf2_stream_cipher(b"legacy_secret", key_seed, salt)
        v1_blob = "enc:" + base64.b64encode(salt + cipher_bytes).decode("ascii")
        self.assertEqual(_generic_decrypt(v1_blob[4:]), "legacy_secret")


if __name__ == "__main__":
    unittest.main()
