#!/usr/bin/env python3
"""Generate Fernet encryption key for IP-Track"""

from cryptography.fernet import Fernet

if __name__ == "__main__":
    key = Fernet.generate_key().decode()
    print(f"\nGenerated Encryption Key:\n{key}\n")
    print("Add this to your .env file:")
    print(f"ENCRYPTION_KEY={key}")
    print()
