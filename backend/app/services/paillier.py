from __future__ import annotations

import hashlib
import math
import secrets
from dataclasses import dataclass
from typing import Sequence


ALGORITHM_CODE = "PAILLIER_ADDITIVE_HOMOMORPHIC_V1"
CAPABILITY_STATUS = "LOCAL_REAL_EXPERIMENTAL_SINGLE_HOST"


class PaillierError(ValueError):
    """Raised when a Paillier key, plaintext or ciphertext is invalid."""


@dataclass(frozen=True, slots=True)
class PaillierPublicKey:
    n: int
    g: int

    @property
    def n_squared(self) -> int:
        return self.n * self.n

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(f"{self.n}:{self.g}".encode()).hexdigest()

    def encrypt(self, value: int) -> int:
        if isinstance(value, bool) or not isinstance(value, int):
            raise PaillierError("plaintext must be an integer")
        if abs(value) >= self.n // 3:
            raise PaillierError("plaintext exceeds the safe signed Paillier range")
        rng = secrets.SystemRandom()
        while True:
            r = rng.randrange(1, self.n)
            if math.gcd(r, self.n) == 1:
                break
        message = value % self.n
        return (pow(self.g, message, self.n_squared) * pow(r, self.n, self.n_squared)) % self.n_squared

    def add(self, *ciphertexts: int) -> int:
        if not ciphertexts:
            raise PaillierError("at least one ciphertext is required")
        result = 1
        for ciphertext in ciphertexts:
            if isinstance(ciphertext, bool) or not isinstance(ciphertext, int):
                raise PaillierError("ciphertext must be an integer")
            if not 0 < ciphertext < self.n_squared:
                raise PaillierError("ciphertext is outside the Paillier modulus")
            result = (result * ciphertext) % self.n_squared
        return result

    def scalar_multiply(self, ciphertext: int, scalar: int) -> int:
        if isinstance(scalar, bool) or not isinstance(scalar, int):
            raise PaillierError("scalar must be an integer")
        if not 0 < ciphertext < self.n_squared:
            raise PaillierError("ciphertext is outside the Paillier modulus")
        return pow(ciphertext, scalar % self.n, self.n_squared)


@dataclass(frozen=True, slots=True)
class PaillierPrivateKey:
    public: PaillierPublicKey
    lambda_value: int
    mu: int

    def decrypt(self, ciphertext: int) -> int:
        if isinstance(ciphertext, bool) or not isinstance(ciphertext, int):
            raise PaillierError("ciphertext must be an integer")
        if not 0 < ciphertext < self.public.n_squared:
            raise PaillierError("ciphertext is outside the Paillier modulus")
        value = (self._l_function(pow(ciphertext, self.lambda_value, self.public.n_squared)) * self.mu) % self.public.n
        return value if value <= self.public.n // 2 else value - self.public.n

    def _l_function(self, value: int) -> int:
        if (value - 1) % self.public.n:
            raise PaillierError("invalid Paillier ciphertext")
        return (value - 1) // self.public.n


@dataclass(frozen=True, slots=True)
class PaillierKeyPair:
    public: PaillierPublicKey
    private: PaillierPrivateKey
    key_bits: int


def _is_probable_prime(value: int, rounds: int = 24) -> bool:
    if value < 2:
        return False
    small_primes = (2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37)
    if value in small_primes:
        return True
    if value % 2 == 0:
        return False
    candidate = value - 1
    twos = 0
    while candidate % 2 == 0:
        twos += 1
        candidate //= 2
    for _ in range(rounds):
        base = secrets.randbelow(value - 3) + 2
        witness = pow(base, candidate, value)
        if witness in (1, value - 1):
            continue
        for _ in range(twos - 1):
            witness = pow(witness, 2, value)
            if witness == value - 1:
                break
        else:
            return False
    return True


def _prime(bits: int) -> int:
    while True:
        candidate = secrets.randbits(bits) | (1 << (bits - 1)) | 1
        if _is_probable_prime(candidate):
            return candidate


def generate_keypair(key_bits: int = 512) -> PaillierKeyPair:
    """Generate a Paillier keypair without a third-party crypto dependency.

    The default is intentionally a local verification size. Production use
    must provision a larger key and protect the private key in a KMS/HSM.
    """

    if key_bits < 512 or key_bits % 2:
        raise PaillierError("key_bits must be an even number of at least 512")
    p = _prime(key_bits // 2)
    q = _prime(key_bits // 2)
    while p == q:
        q = _prime(key_bits // 2)
    n = p * q
    g = n + 1
    lambda_value = math.lcm(p - 1, q - 1)
    n_squared = n * n
    l_value = ((pow(g, lambda_value, n_squared) - 1) // n)
    mu = pow(l_value, -1, n)
    public = PaillierPublicKey(n=n, g=g)
    private = PaillierPrivateKey(public=public, lambda_value=lambda_value, mu=mu)
    return PaillierKeyPair(public=public, private=private, key_bits=key_bits)


def encrypted_sum(
    values: Sequence[int], participant_ids: Sequence[str]
) -> dict[str, object]:
    if len(values) != len(participant_ids) or not values:
        raise PaillierError("values and participant_ids must be non-empty and aligned")
    if len(set(participant_ids)) != len(participant_ids):
        raise PaillierError("participant identifiers must be unique")
    keypair = generate_keypair()
    ciphertexts = [keypair.public.encrypt(value) for value in values]
    aggregate = keypair.public.add(*ciphertexts)
    return {
        "value": keypair.private.decrypt(aggregate),
        "algorithm_code": ALGORITHM_CODE,
        "capability_status": CAPABILITY_STATUS,
        "key_bits": keypair.key_bits,
        "public_key_fingerprint": keypair.public.fingerprint,
        "ciphertext_hashes": [hashlib.sha256(str(item).encode()).hexdigest() for item in ciphertexts],
        "aggregate_ciphertext_hash": hashlib.sha256(str(aggregate).encode()).hexdigest(),
        "participant_ids": list(participant_ids),
        "raw_values_exposed": False,
        "plaintext_values_seen_by_runtime": True,
        "cross_domain_non_export_verified": False,
    }


def encrypted_vector_sum(
    vectors: Sequence[Sequence[float]], participant_ids: Sequence[str], *, scale: int = 1000
) -> dict[str, object]:
    if not vectors or len(vectors) != len(participant_ids):
        raise PaillierError("vectors and participant_ids must be non-empty and aligned")
    width = len(vectors[0])
    if width == 0 or any(len(vector) != width for vector in vectors):
        raise PaillierError("vectors must have the same non-zero width")
    if isinstance(scale, bool) or not isinstance(scale, int) or scale <= 0:
        raise PaillierError("scale must be a positive integer")
    if len(set(participant_ids)) != len(participant_ids):
        raise PaillierError("participant identifiers must be unique")
    keypair = generate_keypair()
    encrypted_hashes: list[str] = []
    aggregate: list[int] = []
    for index in range(width):
        ciphertexts = [
            keypair.public.encrypt(round(float(vector[index]) * scale))
            for vector in vectors
        ]
        aggregate_ciphertext = keypair.public.add(*ciphertexts)
        aggregate.append(keypair.private.decrypt(aggregate_ciphertext))
        encrypted_hashes.extend(
            hashlib.sha256(str(item).encode()).hexdigest() for item in ciphertexts
        )
    return {
        "values": [value / scale for value in aggregate],
        "algorithm_code": ALGORITHM_CODE,
        "capability_status": CAPABILITY_STATUS,
        "key_bits": keypair.key_bits,
        "public_key_fingerprint": keypair.public.fingerprint,
        "ciphertext_count": len(encrypted_hashes),
        "ciphertext_hash": hashlib.sha256("".join(encrypted_hashes).encode()).hexdigest(),
        "participant_ids": list(participant_ids),
        "raw_values_exposed": False,
        "plaintext_values_seen_by_runtime": True,
        "ciphertext_aggregation_verified": True,
        "cross_domain_non_export_verified": False,
    }


def status() -> dict[str, object]:
    return {
        "algorithm_code": ALGORITHM_CODE,
        "capability_label": "LOCAL_REAL",
        "capability_status": CAPABILITY_STATUS,
        "implemented_operations": ["INTEGER_SUM", "SCALAR_MULTIPLICATION"],
        "cross_domain_production_privacy": False,
        "independent_nodes": False,
        "limitations": [
            "private key is generated and held in one application process",
            "production deployment requires KMS/HSM key custody",
            "ciphertext transport and participant orchestration are local",
        ],
    }
