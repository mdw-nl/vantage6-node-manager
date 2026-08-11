"""Unit test for nodemanager/crypto.py's RSA key-pair generation. Just one
test - 4096-bit RSA generation takes real wall-clock time, so this checks
correctness (valid, matching, appropriately-sized PEM key pair) in a single
keygen rather than paying that cost multiple times for marginal extra value.
"""
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization

from nodemanager.crypto import generate_rsa_key_pair


def test_generate_rsa_key_pair_returns_valid_matching_4096_bit_keys():
    private_pem, public_pem = generate_rsa_key_pair()

    assert private_pem.startswith('-----BEGIN RSA PRIVATE KEY-----')
    assert public_pem.startswith('-----BEGIN PUBLIC KEY-----')

    private_key = serialization.load_pem_private_key(private_pem.encode(), password=None)
    public_key = serialization.load_pem_public_key(public_pem.encode())

    assert isinstance(private_key, rsa.RSAPrivateKey)
    assert private_key.key_size == 4096
    # The public key embedded in the returned pair must actually correspond
    # to the private key, not just be *a* validly-formatted public key.
    assert private_key.public_key().public_numbers() == public_key.public_numbers()
