"""RFC 3161 timestamp client (REQ-PROV-01, REQ-AUD-01; ADR-003).

``TsaClient.timestamp(digest)`` sends a ``TimeStampReq`` (SHA-256 message imprint, a random nonce, ``certReq`` true)
to ``TSA_URL`` and, when that fails, to ``TSA_FALLBACK_URL`` (DigiCert primary, FreeTSA fallback by default). A
response is accepted only when:

- the status is granted (or granted with modifications) and a token is present;
- the token is CMS SignedData over a TSTInfo whose message imprint is our SHA-256 digest and whose nonce is ours;
- the signer certificate carried in the token (certReq) has the timeStamping extended key usage, the signed
  ``messageDigest`` attribute matches the TSTInfo, and the signature over the signed attributes verifies with that
  certificate's key (RSA PKCS#1 v1.5, RSA-PSS or ECDSA with SHA-256/384/512).

This proves the token is intact and answers our request. Whether the TSA certificate chains to a trusted root is
checked offline with ``openssl ts -verify`` against the TSA's published CA (``docs/runbooks/verify-offline.md``); the
tests do exactly that against a local test TSA. The stored ``.tsr`` is the whole DER ``TimeStampResp``.

Tests never contact DigiCert or FreeTSA: ``tests/egress.py`` refuses the connection, and the tests pass a fake
transport that answers with ``openssl ts -reply`` from a CA generated at test time.
"""

from __future__ import annotations

import hashlib
import secrets
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import httpx
from asn1crypto import cms, core, tsp
from cryptography import x509
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa
from cryptography.x509.oid import ExtendedKeyUsageOID

from bridge.config import Settings

MAX_RESPONSE_BYTES = 256 * 1024
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


def parse_response(der: bytes, *, digest: bytes, nonce: int) -> TokenInfo:
    """Check a DER ``TimeStampResp`` against our request (see the module docstring) and return the token facts."""
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
        _check_signature(signed_data, tst_der)
        gen_time: datetime = tst_info["gen_time"].native
        return TokenInfo(gen_time, format_serial(tst_info["serial_number"].native), tst_info["policy"].dotted)
    except TsaResponseError:
        raise
    except (ValueError, TypeError, KeyError, IndexError) as exc:  # malformed DER in any field
        raise TsaResponseError(f"the response is not a valid TimeStampResp ({type(exc).__name__})") from exc


def _check_signature(signed_data: cms.SignedData, tst_der: bytes) -> None:
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
    certificate = _signer_certificate(signed_data, signer)
    try:
        usages = certificate.extensions.get_extension_for_class(x509.ExtendedKeyUsage).value
    except x509.ExtensionNotFound:
        usages = x509.ExtendedKeyUsage([])
    if ExtendedKeyUsageOID.TIME_STAMPING not in usages:
        raise TsaResponseError("the signer certificate is not a timestamping certificate")
    # The signature covers the DER SET OF the signed attributes (tag 0x31), not their [0] IMPLICIT encoding.
    to_verify = b"\x31" + signed_attrs.dump()[1:]
    _verify(certificate.public_key(), signer, _HASHES[hash_name](), bytes(signer["signature"].native), to_verify)


def _signer_certificate(signed_data: cms.SignedData, signer: cms.SignerInfo) -> x509.Certificate:
    sid = signer["sid"]
    for choice in signed_data["certificates"] or []:
        if choice.name != "certificate":
            continue
        cert = choice.chosen
        if sid.name == "issuer_and_serial_number":
            match = cert.issuer == sid.chosen["issuer"] and cert.serial_number == sid.chosen["serial_number"].native
        else:
            match = cert.key_identifier == sid.chosen.native
        if match:
            return x509.load_der_x509_certificate(cert.dump())
    raise TsaResponseError("the token does not carry its signer certificate (certReq was set)")


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
    """Timestamps a SHA-256 digest at the first TSA that answers with a valid token."""

    def __init__(
        self, urls: Sequence[str], *, timeout: float = 10.0, transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        if not urls:
            raise ValueError("at least one TSA URL is needed")
        self.urls = tuple(urls)
        self._timeout = timeout
        self._transport = transport

    async def timestamp(self, digest: bytes) -> TimestampToken:
        nonce = secrets.randbits(63) | 1  # positive and never zero
        request = build_request(digest, nonce)
        failures: list[str] = []
        async with httpx.AsyncClient(timeout=self._timeout, transport=self._transport) as client:
            for url in self.urls:
                try:
                    body = await self._post(client, url, request)
                    info = parse_response(body, digest=digest, nonce=nonce)
                except (httpx.HTTPError, TsaResponseError) as exc:
                    failures.append(f"{url}: {exc or type(exc).__name__}")
                    continue
                return TimestampToken(body, info.gen_time, info.serial, info.policy, url)
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


def tsa_client_from_settings(settings: Settings, *, transport: httpx.AsyncBaseTransport | None = None) -> TsaClient:
    urls = [settings.tsa_url] + ([settings.tsa_fallback_url] if settings.tsa_fallback_url else [])
    return TsaClient(urls, timeout=settings.tsa_timeout_seconds, transport=transport)
