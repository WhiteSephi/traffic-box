"""Unit tests for api/crypto.py."""

from __future__ import annotations

import unittest

from src.api.crypto import decrypt_secret, encrypt_secret, _generic_decrypt, _generic_encrypt


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
        """Verify platform-independent PBKDF2 stream cipher works reliably."""
        secret = "cross_platform_linux_test_pwd_99"
        enc = _generic_encrypt(secret)
        self.assertTrue(enc.startswith("enc:"))
        dec = _generic_decrypt(enc[4:])
        self.assertEqual(dec, secret)


if __name__ == "__main__":
    unittest.main()
