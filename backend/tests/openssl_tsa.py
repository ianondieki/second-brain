"""A local RFC 3161 test TSA for the provenance tests (AC-IP-1). Never DigiCert, FreeTSA or any network service.

At test time: a throwaway root CA and a TSA certificate (critical timeStamping extended key usage) are generated with
``cryptography`` into a temporary directory; tokens are then issued with ``openssl ts -reply`` and checked with
``openssl ts -verify``, exactly as anyone would check a stored ``.tsr`` offline (docs/runbooks/verify-offline.md).
``LocalTsa.transport()`` is an httpx transport that answers timestamp queries through ``openssl ts -reply``, so the
production client code runs unchanged against it.

The ``openssl`` command is found on ``OPENSSL_BIN``, then ``PATH``, then (Windows) the copies that ship with Git for
Windows. When none is found the test fails with instructions: it is never skipped (docs/runbooks/dev-setup.md).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

import httpx
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

CONFIG_TEMPLATE = Path(__file__).resolve().parent / "fixtures" / "tsa" / "tsa.cnf"
MISSING_OPENSSL = (
    "The provenance tests need the `openssl` command line (OpenSSL 1.1.1 or 3.x) to issue and verify RFC 3161 "
    "tokens, and none was found. Linux: install your distribution's `openssl` package. macOS: `brew install openssl@3` "
    "and put it on PATH. Windows: install Git for Windows (it ships openssl.exe in %ProgramFiles%\\Git\\usr\\bin), or "
    "put any openssl.exe on PATH, or set OPENSSL_BIN to its full path. See docs/runbooks/dev-setup.md."
)
KeyType = Literal["rsa", "ec"]


def openssl_candidates() -> list[Path]:
    """Where Git for Windows keeps openssl.exe (checked after OPENSSL_BIN and PATH)."""
    roots = [os.environ.get(name) for name in ("ProgramFiles", "ProgramW6432", "ProgramFiles(x86)")]
    local = os.environ.get("LOCALAPPDATA")
    if local:
        roots.append(str(Path(local) / "Programs"))
    return [Path(root) / "Git" / sub / "bin" / "openssl.exe" for root in roots if root for sub in ("usr", "mingw64")]


def find_openssl() -> str:
    configured = os.environ.get("OPENSSL_BIN")
    if configured and Path(configured).is_file():
        return configured
    found = shutil.which("openssl")
    if found:
        return found
    if sys.platform == "win32":
        for candidate in openssl_candidates():
            if candidate.is_file():
                return str(candidate)
    pytest.fail(MISSING_OPENSSL, pytrace=False)


def _name(common_name: str) -> x509.Name:
    return x509.Name(
        [
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Bridge test only"),
            x509.NameAttribute(NameOID.COMMON_NAME, common_name),
        ]
    )


def _key(key_type: KeyType) -> rsa.RSAPrivateKey | ec.EllipticCurvePrivateKey:
    if key_type == "ec":
        return ec.generate_private_key(ec.SECP256R1())
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _usage(*, sign: bool, ca: bool) -> x509.KeyUsage:
    return x509.KeyUsage(
        digital_signature=sign,
        content_commitment=sign,
        key_encipherment=False,
        data_encipherment=False,
        key_agreement=False,
        key_cert_sign=ca,
        crl_sign=ca,
        encipher_only=False,
        decipher_only=False,
    )


@dataclass(frozen=True, slots=True)
class LocalTsa:
    directory: Path
    openssl: str

    @property
    def ca_pem(self) -> Path:
        return self.directory / "ca.pem"

    @property
    def tsa_pem(self) -> Path:
        return self.directory / "tsa.pem"

    @property
    def config(self) -> Path:
        return self.directory / "tsa.cnf"

    @classmethod
    def create(cls, directory: Path, *, key_type: KeyType = "rsa", timestamping_eku: bool = True) -> LocalTsa:
        openssl = find_openssl()
        now = datetime.now(UTC)
        ca_key, tsa_key = _key(key_type), _key(key_type)
        ca = (
            x509.CertificateBuilder()
            .subject_name(_name("Bridge Test TSA Root"))
            .issuer_name(_name("Bridge Test TSA Root"))
            .public_key(ca_key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(days=1))
            .not_valid_after(now + timedelta(days=3650))
            .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
            .add_extension(_usage(sign=False, ca=True), critical=True)
            .add_extension(x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()), critical=False)
            .sign(ca_key, hashes.SHA256())
        )
        builder = (
            x509.CertificateBuilder()
            .subject_name(_name("Bridge Test TSA"))
            .issuer_name(ca.subject)
            .public_key(tsa_key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(days=1))
            .not_valid_after(now + timedelta(days=3650))
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(_usage(sign=True, ca=False), critical=True)
            .add_extension(x509.SubjectKeyIdentifier.from_public_key(tsa_key.public_key()), critical=False)
            .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), critical=False)
        )
        eku = ExtendedKeyUsageOID.TIME_STAMPING if timestamping_eku else ExtendedKeyUsageOID.CODE_SIGNING
        tsa = builder.add_extension(x509.ExtendedKeyUsage([eku]), critical=True).sign(ca_key, hashes.SHA256())
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "ca.pem").write_bytes(ca.public_bytes(serialization.Encoding.PEM))
        (directory / "tsa.pem").write_bytes(tsa.public_bytes(serialization.Encoding.PEM))
        (directory / "tsa.key").write_bytes(
            tsa_key.private_bytes(
                serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
            )
        )
        template = CONFIG_TEMPLATE.read_text(encoding="utf-8")
        (directory / "tsa.cnf").write_text(template.replace("{dir}", directory.as_posix()), encoding="utf-8")
        return cls(directory, openssl)

    def run(self, *args: str) -> subprocess.CompletedProcess[bytes]:
        env = {**os.environ, "OPENSSL_CONF": str(self.config)}
        return subprocess.run([self.openssl, *args], capture_output=True, check=False, timeout=60, env=env)

    def reply(self, query: bytes) -> bytes:
        """``openssl ts -reply`` for a DER TimeStampReq; returns the DER TimeStampResp."""
        stamp = f"{datetime.now(UTC):%H%M%S%f}-{os.getpid()}"
        query_file, reply_file = self.directory / f"q-{stamp}.tsq", self.directory / f"r-{stamp}.tsr"
        query_file.write_bytes(query)
        result = self.run(
            "ts", "-reply", "-config", str(self.config), "-queryfile", str(query_file), "-out", str(reply_file)
        )
        if result.returncode != 0:
            raise RuntimeError("openssl ts -reply failed: " + result.stderr.decode(errors="replace"))
        return reply_file.read_bytes()

    def verify(self, tsr: bytes, *, digest: bytes) -> subprocess.CompletedProcess[bytes]:
        """``openssl ts -verify`` of a stored .tsr against the test CA (what docs/runbooks/verify-offline.md shows)."""
        stamp = f"{datetime.now(UTC):%H%M%S%f}"
        response_file = self.directory / f"v-{stamp}.tsr"
        response_file.write_bytes(tsr)
        return self.run(
            "ts",
            "-verify",
            "-digest",
            digest.hex(),
            "-in",
            str(response_file),
            "-CAfile",
            str(self.ca_pem),
            "-untrusted",
            str(self.tsa_pem),
        )

    def handler(self, request: httpx.Request) -> httpx.Response:
        if request.headers.get("content-type") != "application/timestamp-query":
            return httpx.Response(415)
        return httpx.Response(
            200, content=self.reply(request.content), headers={"Content-Type": "application/timestamp-reply"}
        )

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handler)
