"""RFC 3161 timestamp client (REQ-PROV-01, REQ-AUD-01; ADR-003).

``TsaClient.timestamp(digest)`` sends a ``TimeStampReq`` (SHA-256 message imprint, a random nonce, ``certReq`` true)
to ``TSA_URL`` and, when that fails, to ``TSA_FALLBACK_URL`` (DigiCert primary, FreeTSA fallback by default). A
response is accepted only when:

- the status is granted (or granted with modifications) and a token is present;
- the token is CMS SignedData over a TSTInfo whose message imprint is our SHA-256 digest and whose nonce is ours;
- the signer certificate carried in the token (certReq) has the timeStamping extended key usage as its only purpose,
  in a critical extension (RFC 3161 section 2.3), and is the certificate the signed ESS ``signingCertificate`` or
  ``signingCertificateV2`` attribute names (RFC 2634, RFC 5816: hash and, when given, issuer and serial);
- the signed ``messageDigest`` attribute matches the TSTInfo and the signature over the signed attributes verifies
  with that certificate's key (RSA PKCS#1 v1.5, RSA-PSS or ECDSA with SHA-256/384/512);
- the token's ``genTime`` is within 15 minutes of the local clock;
- the signer certificate chains, through the certificates the token carries, to the trust bundle pinned for that TSA
  URL (``TSA_CA_BUNDLE``, ``TSA_FALLBACK_CA_BUNDLE``: PEM files), every certificate valid at ``genTime``, every issuer
  a CA (and limited to timestamping or any purpose when it states an extended key usage). Certificates inside the
  token are never trusted as anchors.

One attempt (``TSA_DEADLINE_SECONDS``, 30 s by default) covers the primary and the fallback together; each request
also has its per-step ``TSA_TIMEOUT_SECONDS``. A failed attempt raises ``TsaUnavailableError`` and the job retries.

The pinned chain and our nonce are what make a token evidence: the signature alone only proves that someone holding
some timestamping key answered. Outside ``APP_ENV`` dev and test a TSA URL without its bundle fails closed at use
(``tsa_client_from_settings`` raises ``ConfigurationError``); in dev and test the chain check is skipped for a URL
without a bundle (logged). The stored ``.tsr`` is the whole DER ``TimeStampResp``; anyone can check it offline with
``openssl ts -verify`` against the TSA's published CA (``docs/runbooks/verify-offline.md``).

Tests never contact DigiCert or FreeTSA: ``tests/egress.py`` refuses the connection, and the tests pass a fake
transport that answers with ``openssl ts -reply`` from a CA generated at test time, pinned as the trust bundle.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import secrets
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
from asn1crypto import cms, core, tsp
from cryptography import x509
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa
from cryptography.x509.oid import ExtendedKeyUsageOID
from cryptography.x509.verification import (
    Criticality,
    ExtensionPolicy,
    Policy,
    PolicyBuilder,
    Store,
    VerificationError,
)

from bridge.config import ConfigurationError, Settings
from bridge.logging import get_logger

MAX_RESPONSE_BYTES = 256 * 1024
MAX_CLOCK_SKEW = timedelta(minutes=15)
DEFAULT_DEADLINE = 30.0  # seconds for one attempt, primary and fallback together (TSA_DEADLINE_SECONDS)
MAX_CHAIN_DEPTH = 4
UNPINNED_ENVS = frozenset({"dev", "test"})
log = get_logger("bridge.provenance.tsa")
_HASHES: dict[str, type[hashes.HashAlgorithm]] = {
    "sha256": hashes.SHA256,
    "sha384": hashes.SHA384,
    "sha512": hashes.SHA512,
}
_GRANTED = {"granted", "granted_with_mods"}


class _Parts(core.SequenceOf):  # type: ignore[misc]
    """The outer TimeStampResp as raw parts: asn1crypto's schema makes the token mandatory, RFC 3161 does not."""

    _child_spec = core.Any


class TsaError(Exception):
    """Base class of timestamping failures."""


class TsaResponseError(TsaError):
    """The response is not a valid timestamp token for our request."""


class TsaUnavailableError(TsaError):
    """No configured TSA returned a valid token (the job retries with backoff; the record stays "Timestamp pending")."""


@dataclass(frozen=True, slots=True)
class TrustBundle:
    """The pinned trust anchors of one TSA: every certificate in a PEM file (a root, or the issuing CA itself)."""

    anchors: tuple[x509.Certificate, ...] = field(repr=False)
    source: str

    @classmethod
    def from_pem_file(cls, path: Path) -> TrustBundle:
        try:
            data = path.read_bytes()
        except OSError as exc:
            raise ConfigurationError(f"cannot read the TSA CA bundle {path} ({exc.strerror})") from None
        try:
            anchors = tuple(x509.load_pem_x509_certificates(data))
        except ValueError:
            raise ConfigurationError(f"the TSA CA bundle {path} holds no PEM certificate") from None
        return cls(anchors, str(path))


@dataclass(frozen=True, slots=True)
class TsaEndpoint:
    """One TSA URL and its pinned bundle (``None``: no chain check, dev and test only; ``tsa_client_from_settings``)."""

    url: str
    trust: TrustBundle | None


@dataclass(frozen=True, slots=True)
class TokenInfo:
    gen_time: datetime
    serial: str  # "0x" + upper-case hex, as ``openssl ts -reply -text`` prints it
    policy: str


@dataclass(frozen=True, slots=True)
class TimestampToken:
    response: bytes = field(repr=False)  # DER TimeStampResp (.tsr)
    gen_time: datetime
    serial: str
    policy: str
    tsa_url: str


def build_request(digest: bytes, nonce: int) -> bytes:
    """A DER ``TimeStampReq`` for a SHA-256 digest, asking for the signer certificate in the token."""
    if len(digest) != 32:
        raise ValueError("the message imprint is a 32-byte SHA-256 digest")
    request = tsp.TimeStampReq(
        {
            "version": "v1",
            "message_imprint": {"hash_algorithm": {"algorithm": "sha256"}, "hashed_message": digest},
            "nonce": nonce,
            "cert_req": True,
        }
    )
    der: bytes = request.dump()
    return der


def format_serial(serial: int) -> str:
    digits = f"{serial:X}"
    return "0x" + ("0" * (len(digits) % 2)) + digits


def parse_response(
    der: bytes, *, digest: bytes, nonce: int, trust: TrustBundle | None, now: datetime | None = None
) -> TokenInfo:
    """Check a DER ``TimeStampResp`` against our request and the TSA's pinned ``trust`` bundle (see the module
    docstring; ``trust=None`` skips only the chain check) and return the token facts."""
    try:
        parts = _Parts.load(der, strict=True)
        status = tsp.PKIStatusInfo.load(parts[0].dump())["status"].native
        if status not in _GRANTED:
            raise TsaResponseError(f"the TSA refused the request ({status})")
        if len(parts) != 2:
            raise TsaResponseError("the response carries no timestamp token")
        token = tsp.TimeStampResp.load(der, strict=True)["time_stamp_token"]
        if token["content_type"].native != "signed_data":
            raise TsaResponseError("the response carries no signed timestamp token")
        signed_data = token["content"]
        encap = signed_data["encap_content_info"]
        if encap["content_type"].native != "tst_info":
            raise TsaResponseError("the token does not wrap a TSTInfo")
        tst_der: bytes = encap["content"].contents
        tst_info = tsp.TSTInfo.load(tst_der)
        imprint = tst_info["message_imprint"]
        if imprint["hash_algorithm"]["algorithm"].native != "sha256" or imprint["hashed_message"].native != digest:
            raise TsaResponseError("the token timestamps a different message imprint")
        if tst_info["nonce"].native != nonce:
            raise TsaResponseError("the token's nonce does not match the request")
        signer_cert, others = _check_signature(signed_data, tst_der)
        gen_time: datetime = tst_info["gen_time"].native
        if abs(gen_time - (now or datetime.now(UTC))) > MAX_CLOCK_SKEW:
            raise TsaResponseError("the token's time is more than 15 minutes from the local clock")
        if trust is not None:
            _check_chain(signer_cert, others, trust, at=gen_time)
        return TokenInfo(gen_time, format_serial(tst_info["serial_number"].native), tst_info["policy"].dotted)
    except TsaResponseError:
        raise
    except Exception as exc:  # untrusted input: malformed DER, odd keys or certificates fail in many library errors
        raise TsaResponseError(f"the response is not a valid TimeStampResp ({type(exc).__name__})") from exc


def _check_signature(signed_data: cms.SignedData, tst_der: bytes) -> tuple[x509.Certificate, list[x509.Certificate]]:
    """Verify the one signer; return its certificate and the token's other certificates (chain candidates only)."""
    signer_infos = signed_data["signer_infos"]
    if len(signer_infos) != 1:
        raise TsaResponseError("a timestamp token has exactly one signer")
    signer = signer_infos[0]
    hash_name = signer["digest_algorithm"]["algorithm"].native
    if hash_name not in _HASHES:
        raise TsaResponseError(f"unsupported token digest algorithm {hash_name}")
    signed_attrs = signer["signed_attrs"]
    attrs = {attr["type"].native: attr["values"][0].native for attr in signed_attrs}
    if attrs.get("content_type") != "tst_info":
        raise TsaResponseError("the signed content type is not TSTInfo")
    if attrs.get("message_digest") != hashlib.new(hash_name, tst_der).digest():
        raise TsaResponseError("the signed message digest does not match the TSTInfo")
    signer_der, others = _signer_certificate(signed_data, signer)
    certificate = x509.load_der_x509_certificate(signer_der)
    _check_timestamping_usage(certificate)
    _check_ess(signed_attrs, signer_der, certificate)
    # The signature covers the DER SET OF the signed attributes (tag 0x31), not their [0] IMPLICIT encoding.
    to_verify = b"\x31" + signed_attrs.dump()[1:]
    _verify(certificate.public_key(), signer, _HASHES[hash_name](), bytes(signer["signature"].native), to_verify)
    return certificate, [x509.load_der_x509_certificate(der) for der in others]


def _check_timestamping_usage(certificate: x509.Certificate) -> None:
    """RFC 3161 section 2.3: one critical extended key usage extension whose only purpose is timeStamping."""
    try:
        extension = certificate.extensions.get_extension_for_class(x509.ExtendedKeyUsage)
    except x509.ExtensionNotFound:
        raise TsaResponseError("the signer certificate is not a timestamping certificate") from None
    if not extension.critical or list(extension.value) != [ExtendedKeyUsageOID.TIME_STAMPING]:
        raise TsaResponseError(
            "the signer certificate is not a timestamping certificate (critical, sole timeStamping usage)"
        )


_ESS = ("signing_certificate", "signing_certificate_v2")


def _check_ess(signed_attrs: cms.CMSAttributes, signer_der: bytes, certificate: x509.Certificate) -> None:
    """The signed ESS signingCertificate(V2) attribute names the signer certificate (its first ESSCertID)."""
    found = [attr for attr in signed_attrs if attr["type"].native in _ESS]
    if not found:
        raise TsaResponseError("the token does not name its signer certificate (no ESS signingCertificate)")
    for attr in found:
        if len(attr["values"]) != 1:
            raise TsaResponseError("the ESS signingCertificate attribute has one value")
        first = attr["values"][0]["certs"][0]
        if attr["type"].native == "signing_certificate_v2":
            algorithm = first["hash_algorithm"]["algorithm"].native
            if algorithm not in _HASHES:
                raise TsaResponseError(f"unsupported ESS certificate hash {algorithm}")
            expected = hashlib.new(algorithm, signer_der).digest()
        else:
            # ESSCertID (RFC 2634) is SHA-1 by definition (FreeTSA uses it). It only binds the signer certificate;
            # the pinned chain and the signature carry the trust, and a SHA-1 second preimage is not practical.
            expected = hashlib.new("sha1", signer_der).digest()  # noqa: S324
        if not hmac.compare_digest(bytes(first["cert_hash"].native), expected):
            raise TsaResponseError("the ESS signingCertificate does not name the signer certificate")
        issuer_serial = first["issuer_serial"]
        if issuer_serial.native is not None and not _names_certificate(issuer_serial, certificate):
            raise TsaResponseError("the ESS signingCertificate issuer and serial do not match the signer certificate")


def _names_certificate(issuer_serial: tsp.IssuerSerial, certificate: x509.Certificate) -> bool:
    if issuer_serial["serial_number"].native != certificate.serial_number:
        return False
    issuer = certificate.issuer.public_bytes()
    return any(name.name == "directory_name" and name.chosen.dump() == issuer for name in issuer_serial["issuer"])


def _ca_constraints(_policy: Policy, _cert: x509.Certificate, value: x509.BasicConstraints) -> None:
    if not value.ca:
        raise ValueError("an issuer of the TSA certificate is not a CA")


def _ca_key_usage(_policy: Policy, _cert: x509.Certificate, value: x509.KeyUsage | None) -> None:
    if value is not None and not value.key_cert_sign:
        raise ValueError("an issuer of the TSA certificate may not sign certificates")


def _ca_purposes(_policy: Policy, _cert: x509.Certificate, value: x509.ExtendedKeyUsage | None) -> None:
    allowed = {ExtendedKeyUsageOID.TIME_STAMPING, ExtendedKeyUsageOID.ANY_EXTENDED_KEY_USAGE}
    if value is not None and not allowed & set(value):
        raise ValueError("an issuer of the TSA certificate is limited to other purposes than timestamping")


def _leaf_purposes(_policy: Policy, _cert: x509.Certificate, value: x509.ExtendedKeyUsage) -> None:
    if list(value) != [ExtendedKeyUsageOID.TIME_STAMPING]:
        raise ValueError("the TSA certificate's only purpose is timestamping")


# The web PKI defaults of ``cryptography`` would demand a TLS client purpose; a TSA chain states timestamping instead.
# Path building, signatures (web PKI algorithms, RSA >= 2048), validity at genTime, path length and name chaining stay
# the library's.
_CA_POLICY = (
    ExtensionPolicy.permit_all()
    .require_present(x509.BasicConstraints, Criticality.AGNOSTIC, _ca_constraints)
    .may_be_present(x509.KeyUsage, Criticality.AGNOSTIC, _ca_key_usage)
    .may_be_present(x509.ExtendedKeyUsage, Criticality.AGNOSTIC, _ca_purposes)
)
_LEAF_POLICY = ExtensionPolicy.permit_all().require_present(x509.ExtendedKeyUsage, Criticality.CRITICAL, _leaf_purposes)


def _check_chain(
    certificate: x509.Certificate, others: list[x509.Certificate], trust: TrustBundle, *, at: datetime
) -> None:
    verifier = (
        PolicyBuilder()
        .store(Store(list(trust.anchors)))
        .time(at)
        .max_chain_depth(MAX_CHAIN_DEPTH)
        .extension_policies(ca_policy=_CA_POLICY, ee_policy=_LEAF_POLICY)
        .build_client_verifier()
    )
    try:
        verifier.verify(certificate, others)
    except VerificationError as exc:
        raise TsaResponseError(
            f"the TSA certificate does not chain to the CA bundle pinned for this TSA ({trust.source}): {exc}"
        ) from None


def _signer_certificate(signed_data: cms.SignedData, signer: cms.SignerInfo) -> tuple[bytes, list[bytes]]:
    """The DER of the certificate ``signer`` names, and the DER of every other certificate in the token."""
    found: bytes | None = None
    others: list[bytes] = []
    sid = signer["sid"]
    for choice in signed_data["certificates"] or []:
        if choice.name != "certificate":
            continue
        cert = choice.chosen
        if sid.name == "issuer_and_serial_number":
            match = cert.issuer == sid.chosen["issuer"] and cert.serial_number == sid.chosen["serial_number"].native
        else:
            match = cert.key_identifier == sid.chosen.native
        if match and found is None:
            found = cert.dump()
        else:
            others.append(cert.dump())
    if found is None:
        raise TsaResponseError("the token does not carry its signer certificate (certReq was set)")
    return found, others


def _verify(
    public_key: Any, signer: cms.SignerInfo, hash_algorithm: hashes.HashAlgorithm, sig: bytes, data: bytes
) -> None:
    algo = signer["signature_algorithm"].signature_algo
    try:
        if isinstance(public_key, rsa.RSAPublicKey) and algo == "rsassa_pkcs1v15":
            public_key.verify(sig, data, padding.PKCS1v15(), hash_algorithm)
        elif isinstance(public_key, rsa.RSAPublicKey) and algo == "rsassa_pss":
            pss = padding.PSS(mgf=padding.MGF1(hash_algorithm), salt_length=padding.PSS.AUTO)
            public_key.verify(sig, data, pss, hash_algorithm)
        elif isinstance(public_key, ec.EllipticCurvePublicKey) and algo == "ecdsa":
            public_key.verify(sig, data, ec.ECDSA(hash_algorithm))
        else:
            raise TsaResponseError(f"unsupported token signature algorithm {algo}")
    except InvalidSignature as exc:
        raise TsaResponseError("the token signature does not verify") from exc


class TsaClient:
    """Timestamps a SHA-256 digest at the first TSA that answers with a valid token.

    ``timeout`` bounds each network step of one request (httpx: connect, write, and each read, so a TSA that sends a
    byte now and then never trips it); ``deadline`` bounds the whole attempt, primary and fallback together, so a
    slow or dripping TSA cannot hold a worker longer than that."""

    def __init__(
        self,
        endpoints: Sequence[TsaEndpoint],
        *,
        timeout: float = 10.0,
        deadline: float = DEFAULT_DEADLINE,
        transport: httpx.AsyncBaseTransport | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not endpoints:
            raise ValueError("at least one TSA URL is needed")
        if not deadline > 0:
            raise ValueError("the deadline of a timestamp attempt must be positive")
        self.endpoints = tuple(endpoints)
        self.deadline = deadline
        self._timeout = timeout
        self._transport = transport
        self._clock = clock or (lambda: datetime.now(UTC))

    @property
    def urls(self) -> tuple[str, ...]:
        return tuple(endpoint.url for endpoint in self.endpoints)

    async def timestamp(self, digest: bytes) -> TimestampToken:
        nonce = secrets.randbits(63) | 1  # positive and never zero
        request = build_request(digest, nonce)
        failures: list[str] = []
        current = self.endpoints[0].url
        try:
            async with (
                asyncio.timeout(self.deadline),
                httpx.AsyncClient(timeout=self._timeout, transport=self._transport) as client,
            ):
                for endpoint in self.endpoints:
                    current = endpoint.url
                    try:
                        body = await self._post(client, endpoint.url, request)
                        info = parse_response(body, digest=digest, nonce=nonce, trust=endpoint.trust, now=self._clock())
                    except (httpx.HTTPError, TsaResponseError) as exc:
                        failures.append(f"{endpoint.url}: {exc or type(exc).__name__}")
                        continue
                    return TimestampToken(body, info.gen_time, info.serial, info.policy, endpoint.url)
        except TimeoutError:
            failures.append(f"{current}: no answer within the {self.deadline:g} s deadline of this attempt")
        raise TsaUnavailableError("no TSA returned a valid token: " + "; ".join(failures))

    @staticmethod
    async def _post(client: httpx.AsyncClient, url: str, request: bytes) -> bytes:
        headers = {"Content-Type": "application/timestamp-query", "Accept": "application/timestamp-reply"}
        async with client.stream("POST", url, content=request, headers=headers) as response:
            if response.status_code != 200:
                raise TsaResponseError(f"HTTP {response.status_code}")
            body = bytearray()
            async for chunk in response.aiter_bytes():
                body += chunk
                if len(body) > MAX_RESPONSE_BYTES:
                    raise TsaResponseError("the response is too large for a timestamp token")
        return bytes(body)


def _endpoint(settings: Settings, url: str, bundle: Path | None, variable: str) -> TsaEndpoint:
    if bundle is not None:
        return TsaEndpoint(url, TrustBundle.from_pem_file(bundle))
    if settings.app_env not in UNPINNED_ENVS:
        raise ConfigurationError(
            f"{url} needs {variable}: the PEM bundle of that TSA's CA (outside dev and test every TSA is pinned)"
        )
    log.warning("provenance.tsa_unpinned", url=url, variable=variable)
    return TsaEndpoint(url, None)


def tsa_client_from_settings(settings: Settings, *, transport: httpx.AsyncBaseTransport | None = None) -> TsaClient:
    """The TSA client for ``TSA_URL`` (and ``TSA_FALLBACK_URL``), each pinned to its CA bundle; fails closed outside
    dev and test when a bundle is missing or unreadable."""
    endpoints = [_endpoint(settings, settings.tsa_url, settings.tsa_ca_bundle, "TSA_CA_BUNDLE")]
    if settings.tsa_fallback_url:
        endpoints.append(
            _endpoint(settings, settings.tsa_fallback_url, settings.tsa_fallback_ca_bundle, "TSA_FALLBACK_CA_BUNDLE")
        )
    return TsaClient(
        endpoints, timeout=settings.tsa_timeout_seconds, deadline=settings.tsa_deadline_seconds, transport=transport
    )
