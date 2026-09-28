"""REQ-PROV-01: the RFC 3161 client refuses every response that is not an intact token for our request, and falls
back or reports "unavailable" when no TSA answers (the record then stays "Timestamp pending")."""

from __future__ import annotations

import base64
import hashlib
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from asn1crypto import cms, tsp
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from pydantic import SecretStr

from bridge.config import Settings
from bridge.provenance.tsa import (
    MAX_RESPONSE_BYTES,
    TsaClient,
    TsaResponseError,
    TsaUnavailableError,
    build_request,
    format_serial,
    parse_response,
    tsa_client_from_settings,
)
from tests.openssl_tsa import LocalTsa

DIGEST = hashlib.sha256(b"manifest").digest()
NONCE = 0x1234_5678_9ABC


@pytest.fixture(scope="module")
def good_response(local_tsa: LocalTsa) -> bytes:
    return local_tsa.reply(build_request(DIGEST, NONCE))


def tsa_key(local_tsa: LocalTsa) -> rsa.RSAPrivateKey:
    key = serialization.load_pem_private_key((local_tsa.directory / "tsa.key").read_bytes(), password=None)
    assert isinstance(key, rsa.RSAPrivateKey)
    return key


def mutate(der: bytes, change: Callable[[tsp.TimeStampResp, cms.SignedData, cms.SignerInfo], None]) -> bytes:
    response = tsp.TimeStampResp.load(der)
    signed_data = response["time_stamp_token"]["content"]
    change(response, signed_data, signed_data["signer_infos"][0])
    return bytes(response.dump(force=True))


def resign(local_tsa: LocalTsa, signer: cms.SignerInfo, *, pss: bool = False) -> None:
    data = b"\x31" + signer["signed_attrs"].dump(force=True)[1:]
    key = tsa_key(local_tsa)
    if pss:
        pad: Any = padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=32)
        signer["signature_algorithm"] = {
            "algorithm": "rsassa_pss",
            "parameters": {
                "hash_algorithm": {"algorithm": "sha256"},
                "mask_gen_algorithm": {"algorithm": "mgf1", "parameters": {"algorithm": "sha256"}},
                "salt_length": 32,
            },
        }
    else:
        pad = padding.PKCS1v15()
    signer["signature"] = key.sign(data, pad, hashes.SHA256())


def test_the_request_encodes_imprint_nonce_and_cert_req() -> None:
    request = tsp.TimeStampReq.load(build_request(DIGEST, NONCE))
    assert request["message_imprint"]["hash_algorithm"]["algorithm"].native == "sha256"
    assert request["message_imprint"]["hashed_message"].native == DIGEST
    assert request["nonce"].native == NONCE
    assert request["cert_req"].native is True
    with pytest.raises(ValueError, match="32-byte"):
        build_request(b"short", NONCE)


@pytest.mark.parametrize(("serial", "text"), [(1, "0x01"), (0x1A2B, "0x1A2B"), (0xABC, "0x0ABC")])
def test_serials_print_like_openssl(serial: int, text: str) -> None:
    assert format_serial(serial) == text


def test_a_good_response_parses(good_response: bytes) -> None:
    info = parse_response(good_response, digest=DIGEST, nonce=NONCE)
    assert info.policy == "1.2.3.4.1"
    assert abs(info.gen_time - datetime.now(UTC)) < timedelta(minutes=5)


@pytest.mark.parametrize(
    ("digest", "nonce", "message"),
    [
        (hashlib.sha256(b"other").digest(), NONCE, "different message imprint"),
        (DIGEST, NONCE + 1, "nonce"),
    ],
)
def test_a_token_for_another_request_is_refused(good_response: bytes, digest: bytes, nonce: int, message: str) -> None:
    with pytest.raises(TsaResponseError, match=message):
        parse_response(good_response, digest=digest, nonce=nonce)


@pytest.mark.parametrize(
    ("der", "message"),
    [
        (b"not der at all", "not a valid TimeStampResp"),
        (bytes.fromhex("30053003020102"), "refused the request \\(rejection\\)"),
        (bytes.fromhex("30053003020100"), "carries no timestamp token"),
        (bytes.fromhex("3014300302010030" + "0d" + "06092a864886f70d010701a000"), "no signed timestamp token"),
    ],
)
def test_malformed_and_refused_responses(der: bytes, message: str) -> None:
    with pytest.raises(TsaResponseError, match=message):
        parse_response(der, digest=DIGEST, nonce=NONCE)


def _flip_signature(_r: Any, _sd: Any, signer: cms.SignerInfo) -> None:
    signature = bytearray(signer["signature"].native)
    signature[-1] ^= 0x01
    signer["signature"] = bytes(signature)


def _edit_tst(_r: Any, signed_data: cms.SignedData, _s: Any) -> None:
    tst = tsp.TSTInfo.load(signed_data["encap_content_info"]["content"].contents)
    tst["serial_number"] = tst["serial_number"].native + 1
    signed_data["encap_content_info"] = {"content_type": "tst_info", "content": tst}


def _data_content(_r: Any, signed_data: cms.SignedData, _s: Any) -> None:
    content = signed_data["encap_content_info"]["content"].contents
    signed_data["encap_content_info"] = {"content_type": "data", "content": content}


def _two_signers(_r: Any, signed_data: cms.SignedData, signer: cms.SignerInfo) -> None:
    signed_data["signer_infos"] = [signer, signer]


def _sha1_digest(_r: Any, _sd: Any, signer: cms.SignerInfo) -> None:
    signer["digest_algorithm"] = {"algorithm": "sha1"}


def _no_certificates(_r: Any, signed_data: cms.SignedData, _s: Any) -> None:
    signed_data["certificates"] = []


def _dsa_signature(_r: Any, _sd: Any, signer: cms.SignerInfo) -> None:
    signer["signature_algorithm"] = {"algorithm": "sha256_dsa"}


def _wrong_content_type_attr(_r: Any, _sd: Any, signer: cms.SignerInfo) -> None:
    attrs = signer["signed_attrs"]
    for attr in attrs:
        if attr["type"].native == "content_type":
            attr["values"] = ["data"]


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (_flip_signature, "signature does not verify"),
        (_edit_tst, "message digest does not match"),
        (_data_content, "does not wrap a TSTInfo"),
        (_two_signers, "exactly one signer"),
        (_sha1_digest, "unsupported token digest algorithm"),
        (_no_certificates, "signer certificate"),
        (_dsa_signature, "unsupported token signature algorithm"),
        (_wrong_content_type_attr, "signed content type"),
    ],
)
def test_tampered_tokens_are_refused(good_response: bytes, change: Any, message: str) -> None:
    with pytest.raises(TsaResponseError, match=message):
        parse_response(mutate(good_response, change), digest=DIGEST, nonce=NONCE)


def test_a_signer_certificate_without_the_timestamping_eku_is_refused(
    local_tsa: LocalTsa, good_response: bytes
) -> None:
    """The same key and serial re-issued without the EKU: an intact signature is not enough."""
    ca_key = None  # the test CA key is not kept on disk; a self-issued twin is enough to fail the EKU check
    tsa_cert = x509.load_pem_x509_certificate(local_tsa.tsa_pem.read_bytes())
    key = tsa_key(local_tsa)
    twin = (
        x509.CertificateBuilder()
        .subject_name(tsa_cert.subject)
        .issuer_name(tsa_cert.issuer)
        .public_key(key.public_key())
        .serial_number(tsa_cert.serial_number)
        .not_valid_before(tsa_cert.not_valid_before_utc)
        .not_valid_after(tsa_cert.not_valid_after_utc)
        .sign(key, hashes.SHA256())
    )
    assert ca_key is None

    def swap(_r: Any, signed_data: cms.SignedData, _s: Any) -> None:
        from asn1crypto import x509 as asn1_x509

        signed_data["certificates"] = [asn1_x509.Certificate.load(twin.public_bytes(serialization.Encoding.DER))]

    with pytest.raises(TsaResponseError, match="not a timestamping certificate"):
        parse_response(mutate(good_response, swap), digest=DIGEST, nonce=NONCE)


def test_subject_key_identifier_signers_and_rsa_pss_are_accepted(local_tsa: LocalTsa, good_response: bytes) -> None:
    tsa_cert = x509.load_pem_x509_certificate(local_tsa.tsa_pem.read_bytes())
    ski = tsa_cert.extensions.get_extension_for_class(x509.SubjectKeyIdentifier).value.digest

    def by_key_id(_r: Any, _sd: Any, signer: cms.SignerInfo) -> None:
        signer["sid"] = cms.SignerIdentifier(name="subject_key_identifier", value=ski)
        resign(local_tsa, signer, pss=True)

    info = parse_response(mutate(good_response, by_key_id), digest=DIGEST, nonce=NONCE)
    assert info.serial.startswith("0x")

    def unknown_key_id(_r: Any, _sd: Any, signer: cms.SignerInfo) -> None:
        signer["sid"] = cms.SignerIdentifier(name="subject_key_identifier", value=b"\x00" * 20)

    with pytest.raises(TsaResponseError, match="signer certificate"):
        parse_response(mutate(good_response, unknown_key_id), digest=DIGEST, nonce=NONCE)


def _client(handler: Callable[[httpx.Request], httpx.Response], *urls: str) -> TsaClient:
    return TsaClient(urls or ("http://primary.test/tsr",), transport=httpx.MockTransport(handler))


async def test_every_failure_mode_ends_in_unavailable(good_response: bytes) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "down.test":
            raise httpx.ConnectError("connection refused", request=request)
        if request.url.host == "huge.test":
            return httpx.Response(200, content=b"x" * (MAX_RESPONSE_BYTES + 1))
        if request.url.host == "error.test":
            return httpx.Response(500)
        return httpx.Response(200, content=good_response)  # a token for another nonce

    client = _client(handler, "http://down.test/", "http://huge.test/", "http://error.test/", "http://stale.test/")
    with pytest.raises(TsaUnavailableError) as info:
        await client.timestamp(DIGEST)
    text = str(info.value)
    assert "down.test" in text
    assert "too large" in text
    assert "HTTP 500" in text
    assert "nonce" in text


def test_a_client_needs_a_url() -> None:
    with pytest.raises(ValueError, match="at least one TSA URL"):
        TsaClient([])


def test_the_client_comes_from_settings() -> None:
    values: dict[str, Any] = {
        "database_url": SecretStr("postgresql+psycopg://u:p@localhost/db"),
        "secret_key": SecretStr("x" * 32),
        "data_encryption_key": SecretStr(base64.b64encode(bytes(32)).decode()),
        "recovery_code_pepper": SecretStr("p" * 32),
        "_env_file": None,
    }
    both = tsa_client_from_settings(Settings(**values, tsa_url="http://a.test/", tsa_fallback_url="http://b.test/"))
    assert both.urls == ("http://a.test/", "http://b.test/")
    only = tsa_client_from_settings(Settings(**values, tsa_url="http://a.test/", tsa_fallback_url=None))
    assert only.urls == ("http://a.test/",)
