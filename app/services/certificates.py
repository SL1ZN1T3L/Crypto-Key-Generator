"""Генерация X.509: самоподписанные сертификаты и CSR."""

from __future__ import annotations

import asyncio
import ipaddress
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

FIELD_LIMITS = {
    "CN": 64,
    "O": 64,
    "ST": 128,
    "L": 128,
    "Email": 255,
}

_OID_MAP = [
    ("CN", NameOID.COMMON_NAME),
    ("O", NameOID.ORGANIZATION_NAME),
    ("C", NameOID.COUNTRY_NAME),
    ("ST", NameOID.STATE_OR_PROVINCE_NAME),
    ("L", NameOID.LOCALITY_NAME),
    ("Email", NameOID.EMAIL_ADDRESS),
]


@dataclass
class CertRequest:
    is_csr: bool
    details: dict[str, str] = field(default_factory=dict)
    days: int = 365
    passphrase: bytes | None = None
    key_size: int = 3072


@dataclass(frozen=True)
class GeneratedCert:
    document_pem: bytes
    private_key_pem: bytes
    document_suffix: str


def _build_san(cn: str) -> x509.SubjectAlternativeName | None:
    """SAN обязателен: современные клиенты игнорируют CN."""
    cn = cn.strip()
    if not cn:
        return None
    try:
        return x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address(cn))])
    except ValueError:
        pass
    try:
        cn.encode("ascii")
        dns_value = cn
    except UnicodeEncodeError:
        try:
            dns_value = cn.encode("idna").decode("ascii")
        except UnicodeError:
            return None
    return x509.SubjectAlternativeName([x509.DNSName(dns_value)])


def _generate_sync(request: CertRequest) -> GeneratedCert:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=request.key_size)

    encryption = (
        serialization.BestAvailableEncryption(request.passphrase)
        if request.passphrase
        else serialization.NoEncryption()
    )
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=encryption,
    )

    attrs = [
        x509.NameAttribute(oid, request.details[key])
        for key, oid in _OID_MAP
        if request.details.get(key)
    ]
    subject = x509.Name(attrs)
    san = _build_san(request.details.get("CN", ""))

    if request.is_csr:
        builder = x509.CertificateSigningRequestBuilder().subject_name(subject)
        if san is not None:
            builder = builder.add_extension(san, critical=False)
        builder = builder.add_extension(
            x509.BasicConstraints(ca=False, path_length=None), critical=True
        )
        document = builder.sign(private_key, hashes.SHA256())
        return GeneratedCert(
            document_pem=document.public_bytes(serialization.Encoding.PEM),
            private_key_pem=private_pem,
            document_suffix=".csr",
        )

    now = datetime.now(timezone.utc)
    public_key = private_key.public_key()
    builder = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(public_key)
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(days=request.days))
    )
    if san is not None:
        builder = builder.add_extension(san, critical=False)

    builder = builder.add_extension(
        x509.BasicConstraints(ca=False, path_length=None), critical=True
    )
    builder = builder.add_extension(
        x509.KeyUsage(
            digital_signature=True,
            key_encipherment=True,
            content_commitment=False,
            data_encipherment=False,
            key_agreement=False,
            key_cert_sign=False,
            crl_sign=False,
            encipher_only=False,
            decipher_only=False,
        ),
        critical=True,
    )
    builder = builder.add_extension(
        x509.ExtendedKeyUsage([
            x509.oid.ExtendedKeyUsageOID.SERVER_AUTH,
            x509.oid.ExtendedKeyUsageOID.CLIENT_AUTH,
        ]),
        critical=False,
    )
    builder = builder.add_extension(
        x509.SubjectKeyIdentifier.from_public_key(public_key), critical=False
    )

    certificate = builder.sign(private_key, hashes.SHA256())
    return GeneratedCert(
        document_pem=certificate.public_bytes(serialization.Encoding.PEM),
        private_key_pem=private_pem,
        document_suffix=".crt",
    )


async def generate(request: CertRequest) -> GeneratedCert:
    return await asyncio.to_thread(_generate_sync, request)
