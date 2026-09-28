"""REQ-PROV-01: the RFC 3161 client refuses every response that is not an intact token for our request from the TSA
pinned for that URL (its CA bundle, the timeStamping usage, the ESS signing certificate, a time near ours), and falls
back or reports "unavailable" when no TSA answers (the record then stays "Timestamp pending")."""

from __future__ import annotations

import base64
import hashlib
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
from asn1crypto import cms, tsp
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.x509.oid import ExtendedKeyUsageOID
from pydantic import SecretStr

from bridge.config import ConfigurationError, Settings
from bridge.provenance.tsa import (
    MAX_RESPONSE_BYTES,
    TokenInfo,
    TrustBundle,
    TsaClient,
    TsaEndpoint,
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


@pytest.fixture(scope="module")
def trust(local_tsa: LocalTsa) -> TrustBundle:
    return local_tsa.trust


def parse(der: bytes, trust: TrustBundle | None, **overrides: Any) -> TokenInfo:
    return parse_response(der, **{"digest": DIGEST, "nonce": NONCE, "trust": trust, **overrides})


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


def test_a_good_response_parses(good_response: bytes, trust: TrustBundle) -> None:
    info = parse(good_response, trust)
    assert info.policy == "1.2.3.4.1"
    assert abs(info.gen_time - datetime.now(UTC)) < timedelta(minutes=5)


@pytest.mark.parametrize(
    ("digest", "nonce", "message"),
    [
        (hashlib.sha256(b"other").digest(), NONCE, "different message imprint"),
        (DIGEST, NONCE + 1, "nonce"),
    ],
)
def test_a_token_for_another_request_is_refused(
    good_response: bytes, trust: TrustBundle, digest: bytes, nonce: int, message: str
) -> None:
    with pytest.raises(TsaResponseError, match=message):
        parse(good_response, trust, digest=digest, nonce=nonce)


@pytest.mark.parametrize(
    ("der", "message"),
    [
        (b"not der at all", "not a valid TimeStampResp"),
        (bytes.fromhex("30053003020102"), "refused the request \\(rejection\\)"),
        (bytes.fromhex("30053003020100"), "carries no timestamp token"),
        (bytes.fromhex("3014300302010030" + "0d" + "06092a864886f70d010701a000"), "no signed timestamp token"),
    ],
)
def test_malformed_and_refused_responses(der: bytes, trust: TrustBundle, message: str) -> None:
    with pytest.raises(TsaResponseError, match=message):
        parse(der, trust)


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
def test_tampered_tokens_are_refused(good_response: bytes, trust: TrustBundle, change: Any, message: str) -> None:
    with pytest.raises(TsaResponseError, match=message):
        parse(mutate(good_response, change), trust)


def _swap_certificate(certificate: x509.Certificate) -> Callable[[Any, cms.SignedData, Any], None]:
    def swap(_r: Any, signed_data: cms.SignedData, _s: Any) -> None:
        from asn1crypto import x509 as asn1_x509

        der = certificate.public_bytes(serialization.Encoding.DER)
        signed_data["certificates"] = [asn1_x509.Certificate.load(der)]

    return swap


@pytest.mark.parametrize(
    ("eku", "critical"),
    [
        (None, True),  # no extended key usage at all
        ([ExtendedKeyUsageOID.CODE_SIGNING], True),
        ([ExtendedKeyUsageOID.TIME_STAMPING], False),  # RFC 3161 2.3: the extension MUST be critical
        ([ExtendedKeyUsageOID.TIME_STAMPING, ExtendedKeyUsageOID.CODE_SIGNING], True),  # and timestamping the only one
    ],
)
def test_a_signer_certificate_that_is_not_only_for_timestamping_is_refused(
    local_tsa: LocalTsa, good_response: bytes, trust: TrustBundle, eku: Any, critical: bool
) -> None:
    """The same key and serial re-issued by the same CA with another extended key usage: an intact signature and a
    good chain are not enough."""
    twin = local_tsa.twin(eku=eku, critical=critical)
    with pytest.raises(TsaResponseError, match="not a timestamping certificate"):
        parse(mutate(good_response, _swap_certificate(twin)), trust)


def test_a_token_from_a_stranger_tsa_is_refused(local_tsa: LocalTsa, tmp_path: Path) -> None:
    """A TSA with its own CA answers correctly (right imprint and nonce, intact signature, its root in the token):
    refused, because it does not chain to the bundle pinned for the URL; the token's own certificates are never
    trusted."""
    stranger = LocalTsa.create(tmp_path / "stranger")
    token = stranger.reply(build_request(DIGEST, NONCE))
    assert parse(token, stranger.trust).policy == "1.2.3.4.1"  # a well-formed token for its own CA
    with pytest.raises(TsaResponseError, match="does not chain to the CA bundle pinned for this TSA"):
        parse(token, local_tsa.trust)


async def test_the_client_refuses_a_stranger_answering_at_the_pinned_url(local_tsa: LocalTsa, tmp_path: Path) -> None:
    stranger = LocalTsa.create(tmp_path / "stranger")
    client = TsaClient([local_tsa.endpoint("http://tsa.test/tsr")], transport=stranger.transport())
    with pytest.raises(TsaUnavailableError, match="does not chain"):
        await client.timestamp(DIGEST)


@pytest.mark.parametrize(
    ("valid_from", "valid_until"),
    [(timedelta(days=-10), timedelta(days=-1)), (timedelta(days=1), timedelta(days=10))],
    ids=["expired", "not-yet-valid"],
)
def test_a_tsa_certificate_invalid_at_gen_time_is_refused(
    tmp_path: Path, valid_from: timedelta, valid_until: timedelta
) -> None:
    tsa = LocalTsa.create(tmp_path / "tsa", valid_from=valid_from, valid_until=valid_until)
    token = tsa.reply(build_request(DIGEST, NONCE))
    with pytest.raises(TsaResponseError, match="not valid at validation time"):
        parse(token, tsa.trust)


@pytest.mark.parametrize(
    "eku",
    [
        # DigiCert's shape: an intermediate limited to timestamping. cryptography's web PKI defaults refuse this chain
        # ("Neither EKU nor anyEKU could be found": they want TLS client auth), so this case pins the TSA CA policy.
        [ExtendedKeyUsageOID.TIME_STAMPING],
        None,  # FreeTSA's shape: a CA that states no extended key usage
        [ExtendedKeyUsageOID.ANY_EXTENDED_KEY_USAGE],
    ],
    ids=["timestamping-only", "no-eku", "any-eku"],
)
def test_a_chain_through_an_intermediate_allowed_to_timestamp_is_accepted(tmp_path: Path, eku: Any) -> None:
    """Root, intermediate, TSA. The token carries the intermediate; the bundle pins the root (or the intermediate
    itself)."""
    tsa = LocalTsa.create(tmp_path / "tsa", intermediate=True, intermediate_eku=eku)
    token = tsa.reply(build_request(DIGEST, NONCE))
    assert parse(token, tsa.trust).serial.startswith("0x")
    assert parse(token, TrustBundle.from_pem_file(tsa.directory / "issuer.pem")).serial.startswith("0x")
    assert tsa.verify(token, digest=DIGEST).returncode == 0


@pytest.mark.parametrize(
    ("eku", "key_cert_sign"),
    [
        ([ExtendedKeyUsageOID.SERVER_AUTH], True),  # a TLS CA may not vouch for a timestamping certificate
        ([ExtendedKeyUsageOID.CODE_SIGNING, ExtendedKeyUsageOID.CLIENT_AUTH], True),
        ([ExtendedKeyUsageOID.TIME_STAMPING], False),  # a CA certificate without keyCertSign issues nothing
    ],
    ids=["tls-server-ca", "code-signing-ca", "no-key-cert-sign"],
)
def test_a_chain_through_an_intermediate_not_allowed_to_timestamp_is_refused(
    tmp_path: Path, eku: Any, key_cert_sign: bool
) -> None:
    """The root is pinned and every signature is intact, but the intermediate may not issue a TSA certificate: its
    extended key usage excludes timestamping, or its key usage excludes certificate signing."""
    tsa = LocalTsa.create(
        tmp_path / "tsa", intermediate=True, intermediate_eku=eku, intermediate_key_cert_sign=key_cert_sign
    )
    token = tsa.reply(build_request(DIGEST, NONCE))
    assert parse(token, None).serial.startswith("0x")  # a well-formed, correctly signed token
    with pytest.raises(TsaResponseError, match="does not chain to the CA bundle pinned for this TSA"):
        parse(token, tsa.trust)


def _signing_certificate_attr(signer: cms.SignerInfo) -> Any:
    for attr in signer["signed_attrs"]:
        if attr["type"].native == "signing_certificate_v2":
            return attr
    raise AssertionError("openssl always adds signingCertificateV2 with ess_cert_id_alg = sha256")


def _ess_v1(local_tsa: LocalTsa) -> Callable[[Any, Any, cms.SignerInfo], None]:
    der = x509.load_pem_x509_certificate(local_tsa.tsa_pem.read_bytes()).public_bytes(serialization.Encoding.DER)

    def change(_r: Any, _sd: Any, signer: cms.SignerInfo) -> None:
        attrs = [a for a in signer["signed_attrs"] if a["type"].native != "signing_certificate_v2"]
        sha1 = hashlib.sha1(der).digest()  # noqa: S324 - ESSCertID is SHA-1 by definition (RFC 2634)
        v1 = {"type": "signing_certificate", "values": [{"certs": [{"cert_hash": sha1}]}]}
        signer["signed_attrs"] = [*attrs, v1]
        resign(local_tsa, signer)

    return change


def test_an_ess_v1_signing_certificate_is_accepted(local_tsa: LocalTsa, good_response: bytes) -> None:
    """FreeTSA names its certificate with ESSCertID (SHA-1): accepted when it names the signer."""
    assert parse(mutate(good_response, _ess_v1(local_tsa)), local_tsa.trust).serial.startswith("0x")


def _without_ess(local_tsa: LocalTsa) -> Callable[[Any, Any, cms.SignerInfo], None]:
    def change(_r: Any, _sd: Any, signer: cms.SignerInfo) -> None:
        signer["signed_attrs"] = [a for a in signer["signed_attrs"] if a["type"].native != "signing_certificate_v2"]
        resign(local_tsa, signer)

    return change


def _other_cert_hash(local_tsa: LocalTsa) -> Callable[[Any, Any, cms.SignerInfo], None]:
    def change(_r: Any, _sd: Any, signer: cms.SignerInfo) -> None:
        _signing_certificate_attr(signer)["values"] = [{"certs": [{"cert_hash": hashlib.sha256(b"other").digest()}]}]
        resign(local_tsa, signer)

    return change


def _other_serial(local_tsa: LocalTsa) -> Callable[[Any, Any, cms.SignerInfo], None]:
    cert = x509.load_pem_x509_certificate(local_tsa.tsa_pem.read_bytes())
    der = cert.public_bytes(serialization.Encoding.DER)
    from asn1crypto import x509 as asn1_x509

    issuer = asn1_x509.Name.load(cert.issuer.public_bytes())

    def change(_r: Any, _sd: Any, signer: cms.SignerInfo) -> None:
        ess_id = {
            "cert_hash": hashlib.sha256(der).digest(),
            "issuer_serial": {
                "issuer": [asn1_x509.GeneralName(name="directory_name", value=issuer)],
                "serial_number": cert.serial_number + 1,
            },
        }
        _signing_certificate_attr(signer)["values"] = [{"certs": [ess_id]}]
        resign(local_tsa, signer)

    return change


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (_without_ess, "no ESS signingCertificate"),
        (_other_cert_hash, "does not name the signer certificate"),
        (_other_serial, "issuer and serial do not match"),
    ],
)
def test_the_ess_signing_certificate_must_name_the_signer(
    local_tsa: LocalTsa, good_response: bytes, change: Any, message: str
) -> None:
    """The signed ESS attribute binds the signer certificate (RFC 5816); a token whose attribute is missing or names
    another certificate is refused even though its signature is intact (the tokens are re-signed)."""
    with pytest.raises(TsaResponseError, match=message):
        parse(mutate(good_response, change(local_tsa)), local_tsa.trust)


def test_a_token_time_far_from_the_local_clock_is_refused(good_response: bytes, trust: TrustBundle) -> None:
    gen_time = parse(good_response, trust).gen_time
    assert parse(good_response, trust, now=gen_time + timedelta(minutes=14)).gen_time == gen_time
    assert parse(good_response, trust, now=gen_time - timedelta(minutes=14)).gen_time == gen_time
    for skew in (timedelta(minutes=16), -timedelta(minutes=16)):
        with pytest.raises(TsaResponseError, match="more than 15 minutes from the local clock"):
            parse(good_response, trust, now=gen_time + skew)


async def test_the_client_checks_the_time_against_its_clock(local_tsa: LocalTsa) -> None:
    ahead = datetime.now(UTC) + timedelta(hours=1)
    endpoint = local_tsa.endpoint("http://tsa.test/tsr")
    client = TsaClient([endpoint], transport=local_tsa.transport(), clock=lambda: ahead)
    with pytest.raises(TsaUnavailableError, match="15 minutes"):
        await client.timestamp(DIGEST)


def test_subject_key_identifier_signers_and_rsa_pss_are_accepted(
    local_tsa: LocalTsa, good_response: bytes, trust: TrustBundle
) -> None:
    tsa_cert = x509.load_pem_x509_certificate(local_tsa.tsa_pem.read_bytes())
    ski = tsa_cert.extensions.get_extension_for_class(x509.SubjectKeyIdentifier).value.digest

    def by_key_id(_r: Any, _sd: Any, signer: cms.SignerInfo) -> None:
        signer["sid"] = cms.SignerIdentifier(name="subject_key_identifier", value=ski)
        resign(local_tsa, signer, pss=True)

    info = parse(mutate(good_response, by_key_id), trust)
    assert info.serial.startswith("0x")

    def unknown_key_id(_r: Any, _sd: Any, signer: cms.SignerInfo) -> None:
        signer["sid"] = cms.SignerIdentifier(name="subject_key_identifier", value=b"\x00" * 20)

    with pytest.raises(TsaResponseError, match="signer certificate"):
        parse(mutate(good_response, unknown_key_id), trust)


def _client(handler: Callable[[httpx.Request], httpx.Response], *urls: str) -> TsaClient:
    endpoints = [TsaEndpoint(url, None) for url in urls or ("http://primary.test/tsr",)]
    return TsaClient(endpoints, transport=httpx.MockTransport(handler))


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


def _settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "database_url": SecretStr("postgresql+psycopg://u:p@localhost/db"),
        "secret_key": SecretStr("x" * 32),
        "data_encryption_key": SecretStr(base64.b64encode(bytes(32)).decode()),
        "recovery_code_pepper": SecretStr("p" * 32),
        "tsa_ca_bundle": None,
        "tsa_fallback_ca_bundle": None,
        "_env_file": None,
    }
    values.update(overrides)
    return Settings(**values)


def test_the_client_comes_from_settings(local_tsa: LocalTsa) -> None:
    both = tsa_client_from_settings(
        _settings(
            app_env="staging",
            tsa_url="http://a.test/",
            tsa_fallback_url="http://b.test/",
            tsa_ca_bundle=local_tsa.ca_pem,
            tsa_fallback_ca_bundle=local_tsa.ca_pem,
        )
    )
    assert both.urls == ("http://a.test/", "http://b.test/")
    assert all(e.trust is not None and e.trust.source == str(local_tsa.ca_pem) for e in both.endpoints)
    only = tsa_client_from_settings(_settings(app_env="test", tsa_url="http://a.test/", tsa_fallback_url=None))
    assert only.urls == ("http://a.test/",)
    assert only.endpoints[0].trust is None  # dev and test only: no chain check without a bundle


@pytest.mark.parametrize("app_env", ["staging", "production"])
def test_outside_dev_and_test_every_tsa_url_needs_its_bundle(local_tsa: LocalTsa, app_env: str) -> None:
    env: dict[str, Any] = {"app_env": app_env}
    if app_env == "production":
        env |= {
            "email_provider": "postmark",
            "postmark_server_token": SecretStr("token"),
            "public_base_url": "https://bridge.example",
        }
    with pytest.raises(ConfigurationError, match="needs TSA_CA_BUNDLE"):
        tsa_client_from_settings(_settings(**env, tsa_fallback_url=None))
    with pytest.raises(ConfigurationError, match="needs TSA_FALLBACK_CA_BUNDLE"):
        tsa_client_from_settings(_settings(**env, tsa_ca_bundle=local_tsa.ca_pem))


def test_an_unreadable_or_empty_bundle_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(ConfigurationError, match="cannot read the TSA CA bundle"):
        TrustBundle.from_pem_file(tmp_path / "missing.pem")
    empty = tmp_path / "empty.pem"
    empty.write_text("not a certificate\n", encoding="utf-8")
    with pytest.raises(ConfigurationError, match="holds no PEM certificate"):
        tsa_client_from_settings(_settings(app_env="dev", tsa_ca_bundle=empty))


def test_random_corruption_only_ever_raises_tsa_response_error(good_response: bytes, trust: TrustBundle) -> None:
    """Untrusted bytes: whatever breaks inside the ASN.1 or X.509 libraries surfaces as TsaResponseError."""
    import random

    rng = random.Random(20260928)
    for _ in range(1500):
        corrupted = bytearray(good_response)
        for _ in range(rng.randint(1, 4)):
            corrupted[rng.randrange(len(corrupted))] = rng.randrange(256)
        if rng.random() < 0.1:
            corrupted = corrupted[: rng.randrange(len(corrupted))]
        try:
            parse(bytes(corrupted), trust)
        except TsaResponseError:
            continue
