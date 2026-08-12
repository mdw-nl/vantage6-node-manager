"""RSA key-pair generation for node encryption."""
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend


def generate_rsa_key_pair():
    """
    Generate a new RSA key pair for encryption.

    Returns:
        tuple: (private_key_pem, public_key_pem) as strings
    """
    try:
        # Generate private key (4096 bits for strong security)
        private_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=4096,
            backend=default_backend()
        )

        # Serialize private key to PEM format
        private_key_pem = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption()
        ).decode('utf-8')

        # Generate public key from private key
        public_key = private_key.public_key()

        # Serialize public key to PEM format
        public_key_pem = public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo
        ).decode('utf-8')

        return private_key_pem, public_key_pem
    except Exception as e:
        print(f"Error generating RSA key pair: {e}")
        return None, None
