from cryptography.fernet import Fernet
from core.config import settings
import base64


class CredentialEncryption:
    """Handle encryption and decryption of switch credentials"""

    def __init__(self):
        # Ensure the key is properly formatted
        key = settings.ENCRYPTION_KEY.encode() if isinstance(settings.ENCRYPTION_KEY, str) else settings.ENCRYPTION_KEY
        self.cipher = Fernet(key)

    def encrypt(self, plaintext: str) -> str:
        """Encrypt a plaintext string"""
        if not plaintext:
            return ""
        encrypted = self.cipher.encrypt(plaintext.encode())
        return base64.b64encode(encrypted).decode()

    def decrypt(self, encrypted_text: str) -> str:
        """Decrypt an encrypted string"""
        if not encrypted_text:
            return ""
        decoded = base64.b64decode(encrypted_text.encode())
        decrypted = self.cipher.decrypt(decoded)
        return decrypted.decode()


# Singleton instance
credential_encryption = CredentialEncryption()
