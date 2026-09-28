"""A local RFC 3161 test TSA for the provenance tests (AC-IP-1). Never DigiCert, FreeTSA or any network service.

At test time: a throwaway root CA (optionally an intermediate CA, limited to timestamping as DigiCert's is) and
a TSA certificate (critical, sole timeStamping extended key usage) are generated with ``cryptography`` into a
temporary directory; tokens are then issued with ``openssl ts -reply`` and checked with ``openssl ts -verify``, exactly
as anyone would check a stored ``.tsr`` offline (docs/runbooks/verify-offline.md). ``LocalTsa.transport()`` is an
httpx transport that answers timestamp queries through ``openssl ts -reply``, so the production client code runs
unchanged against it; ``LocalTsa.trust`` is the pinned bundle (the root) that client checks the chain against.

The ``openssl`` command is found on ``OPENSSL_BIN``, then ``PATH``, then (Windows) the copies that ship with Git for
Windows. When none is found the test fails with instructions: it is never skipped (docs/runbooks/dev-setup.md).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

import httpx
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID, ObjectIdentifier

from bridge.provenance.tsa import TrustBundle, TsaEndpoint

CONFIG_TEMPLATE = Path(__file__).resolve().parent / "fixtures" / "tsa" / "tsa.cnf"
MISSING_OPENSSL = (
    "The provenance tests need the `openssl` command line (OpenSSL 1.1.1 or 3.x) to issue and verify RFC 3161 "
    "tokens, and none was found. Linux: install your distribution's `openssl` package. macOS: `brew install openssl@3` "
    "and put it on PATH. Windows: install Git for Windows (it ships openssl.exe in %ProgramFiles%\\Git\\usr\\bin), or "
    "put any openssl.exe on PATH, or set OPENSSL_BIN to its full path. See docs/runbooks/dev-setup.md."
)
KeyType = Literal["rsa", "ec"]
TIMESTAMPING_ONLY: tuple[ObjectIdentifier, ...] = (ExtendedKeyUsageOID.TIME_STAMPING,)
PrivateKey = rsa.RSAPrivateKey | ec.EllipticCurvePrivateKey


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


def _key(key_type: KeyType) -> PrivateKey:
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


def _pem(path: Path, *certs: x509.Certificate) -> None:
    path.write_bytes(b"".join(c.public_bytes(serialization.Encoding.PEM) for c in certs))


def _private_pem(path: Path, key: PrivateKey) -> None:
    path.write_bytes(
        key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    )


def _load_key(path: Path) -> PrivateKey:
    key = serialization.load_pem_private_key(path.read_bytes(), password=None)
    assert isinstance(key, rsa.RSAPrivateKey | ec.EllipticCurvePrivateKey)
    return key


def _ca(
    subject: str,
    key: PrivateKey,
    issuer: x509.Name,
    issuer_key: PrivateKey,
    now: datetime,
    *,
    intermediate: bool,
    eku: Sequence[ObjectIdentifier] | None = None,
    key_cert_sign: bool = True,
) -> x509.Certificate:
    builder = (
        x509.CertificateBuilder()
        .subject_name(_name(subject))
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=3650))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0 if intermediate else 1), critical=True)
        .add_extension(_usage(sign=not key_cert_sign, ca=key_cert_sign), critical=True)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
    )
    if intermediate:
        builder = builder.add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(issuer_key.public_key()), critical=False
        )
    if eku is not None:
        builder = builder.add_extension(x509.ExtendedKeyUsage(list(eku)), critical=False)
    return builder.sign(issuer_key, hashes.SHA256())


@dataclass(frozen=True, slots=True)
class LocalTsa:
    directory: Path
    openssl: str

    @property
    def ca_pem(self) -> Path:
        """The root certificate: the pinned trust bundle (``TSA_CA_BUNDLE``) and ``openssl ts -verify -CAfile``."""
        return self.directory / "ca.pem"

    @property
    def tsa_pem(self) -> Path:
        return self.directory / "tsa.pem"

    @property
    def config(self) -> Path:
        return self.directory / "tsa.cnf"

    @property
    def trust(self) -> TrustBundle:
        return TrustBundle.from_pem_file(self.ca_pem)

    def endpoint(self, url: str) -> TsaEndpoint:
        """This TSA at ``url``, pinned to its own root."""
        return TsaEndpoint(url, self.trust)

    @classmethod
    def create(
        cls,
        directory: Path,
        *,
        key_type: KeyType = "rsa",
        intermediate: bool = False,
        intermediate_eku: Sequence[ObjectIdentifier] | None = TIMESTAMPING_ONLY,
        intermediate_key_cert_sign: bool = True,
        valid_from: timedelta = timedelta(days=-1),
        valid_until: timedelta = timedelta(days=3650),
    ) -> LocalTsa:
        """A test TSA. ``valid_from``/``valid_until`` place the TSA certificate's validity relative to now (openssl
        signs with it either way, so an expired or not-yet-valid certificate can be tested).

        ``intermediate`` puts an issuing CA between the root and the TSA certificate. By default it is limited to
        timestamping, like DigiCert's "Trusted G4 TimeStamping" CA; ``intermediate_eku`` gives it other extended key
        usages (``None``: no extension, like FreeTSA's CA) and ``intermediate_key_cert_sign=False`` takes away its
        keyCertSign usage (openssl issues tokens either way: it never checks the chain it sends)."""
        openssl = find_openssl()
        now = datetime.now(UTC)
        root_key, tsa_key = _key(key_type), _key(key_type)
        root_name = _name("Bridge Test TSA Root")
        root = _ca("Bridge Test TSA Root", root_key, root_name, root_key, now, intermediate=False)
        chain = [root]
        issuer, issuer_key = root, root_key
        if intermediate:
            issuer_key = _key(key_type)
            issuer = _ca(
                "Bridge Test TimeStamping CA",
                issuer_key,
                root.subject,
                root_key,
                now,
                intermediate=True,
                eku=intermediate_eku,
                key_cert_sign=intermediate_key_cert_sign,
            )
            chain = [issuer, root]
        tsa = (
            x509.CertificateBuilder()
            .subject_name(_name("Bridge Test TSA"))
            .issuer_name(issuer.subject)
            .public_key(tsa_key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now + valid_from)
            .not_valid_after(now + valid_until)
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(_usage(sign=True, ca=False), critical=True)
            .add_extension(x509.SubjectKeyIdentifier.from_public_key(tsa_key.public_key()), critical=False)
            .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(issuer_key.public_key()), critical=False)
            .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.TIME_STAMPING]), critical=True)
            .sign(issuer_key, hashes.SHA256())
        )
        directory.mkdir(parents=True, exist_ok=True)
        _pem(directory / "ca.pem", root)
        _pem(directory / "chain.pem", *chain)  # the certificates each token carries besides the signer's
        _pem(directory / "issuer.pem", issuer)
        _pem(directory / "tsa.pem", tsa)
        _private_pem(directory / "tsa.key", tsa_key)
        _private_pem(directory / "issuer.key", issuer_key)  # test-only: issues the twins below
        template = CONFIG_TEMPLATE.read_text(encoding="utf-8")
        (directory / "tsa.cnf").write_text(template.replace("{dir}", directory.as_posix()), encoding="utf-8")
        return cls(directory, openssl)

    def twin(self, *, eku: list[ObjectIdentifier] | None, critical: bool = True) -> x509.Certificate:
        """The TSA certificate re-issued by the same CA with the same key and serial but another extended key usage
        (openssl refuses to sign with such a certificate, so tests swap it into a token)."""
        original = x509.load_pem_x509_certificate(self.tsa_pem.read_bytes())
        issuer = x509.load_pem_x509_certificate((self.directory / "issuer.pem").read_bytes())
        builder = (
            x509.CertificateBuilder()
            .subject_name(original.subject)
            .issuer_name(issuer.subject)
            .public_key(_load_key(self.directory / "tsa.key").public_key())
            .serial_number(original.serial_number)
            .not_valid_before(original.not_valid_before_utc)
            .not_valid_after(original.not_valid_after_utc)
        )
        if eku is not None:
            builder = builder.add_extension(x509.ExtendedKeyUsage(eku), critical=critical)
        return builder.sign(_load_key(self.directory / "issuer.key"), hashes.SHA256())

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
