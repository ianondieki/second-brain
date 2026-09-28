# Verify an authorship certificate offline

## Purpose

Check a Bridge authorship certificate without trusting Bridge's servers: recompute the content hash from the
registered manifest, check the RFC 3161 timestamp token with `openssl ts -verify`, and check Bridge's Ed25519
signature against the published key. Anyone can do this: an owner, an organisation, a lawyer, a court expert.

What a passing check proves: this exact manifest (every Tier-1 and Tier-2 field, the attachment hashes and the salted
owner reference) existed no later than the time in the token, and Bridge registered it under this certificate id.
What it does not prove: [[COPY-REVIEW]] the certificate footer says it exactly, "This certificate is evidence of what
was submitted and when. It is not a patent, copyright registration or guarantee against independent development or
misuse."

Requirements: REQ-PROV-01 (registration pipeline), REQ-PROV-02 (certificate, `/verify`, this guide), REQ-AUD-01
(transparency roots); `docs/spec/06-feature-modules.md` 6.4 items 1, 2 and 4; ADR-003.

## Preconditions

- OpenSSL 3.0 or later (`openssl version`). Linux and macOS: the system or Homebrew `openssl@3`. Windows: Git Bash
  (Git for Windows ships `openssl` and `printf`); run every command below in Git Bash.
- `curl`, and `sha256sum` (or `openssl dgst -sha256`).
- The certificate id (printed on the certificate and in its QR code link `https://<host>/verify/<CERT_ID>`).
- To recompute the hash you need the manifest file. The owner downloads it from the certificate page (API:
  `GET /api/provenance/certificates/<CERT_ID>/manifest.json`, owner only); an owner may hand it to anyone who should
  check it. Without the manifest you can still check the token and the signature over the published hash.

Replace `https://bridge.example` below with the platform's address, and `CERT_ID` with the certificate id.

## 1. Fetch the public facts

```bash
HOST=https://bridge.example
CERT=CERT_ID
curl -fsS "$HOST/api/verify/$CERT"                          # content_hash, timestamp, tsa_serial, key_id, signature
curl -fsS -o token.tsr "$HOST/api/verify/$CERT/timestamp.tsr" # the RFC 3161 token (DER TimeStampResp)
curl -fsS "$HOST/.well-known/provenance-keys.json"           # Bridge's public signing keys
```

Copy `content_hash`, `signature` and `key_id` from the first answer into shell variables:

```bash
HASH=<content_hash hex>
SIG=<signature base64>
KID=<key_id, e.g. ed25519:0123456789abcdef>
```

From the keys document, save the `pem` of the key whose `kid` equals `$KID` as `key.pem` (keep its line breaks).
Keep a copy of `provenance-keys.json` itself: Bridge publishes retired keys too, so old certificates stay checkable.

`/verify` shows only the hash, the timestamp, the TSA serial, the status and the signature material, never the
owner's name or the title. "Timestamp pending" means the token is not stored yet: check again later.

## 2. Recompute the content hash

```bash
sha256sum manifest.json            # or: openssl dgst -sha256 -r manifest.json
```

The first field must equal `$HASH`. The manifest is RFC 8785 canonical JSON: do not open and re-save it in an editor,
reformat it or change its line endings; one changed byte gives a different hash (that is the point). To check a file
against Bridge directly, upload it at `https://<host>/verify` (API: `POST /api/verify` with the raw file as the body);
the answer is match or no match.

## 3. Check the timestamp token

Read what the token says, and compare its serial and time with the certificate:

```bash
openssl ts -reply -in token.tsr -text              # "Serial number" must equal tsa_serial; "Time stamp" is the time
openssl ts -reply -in token.tsr -token_out -out token.der
openssl pkcs7 -inform DER -in token.der -print_certs -noout   # which TSA signed it, and its issuer
```

Verify the token against the manifest (or, without the manifest, against the hash), trusting only the TSA's root
certificate:

```bash
openssl ts -verify -data manifest.json -in token.tsr -CAfile tsa-root.pem
openssl ts -verify -digest "$HASH" -in token.tsr -CAfile tsa-root.pem
```

Both print `Verification: OK`. `tsa-root.pem` is the root certificate of the TSA that issued the token (the last
`issuer` printed above), fetched from that TSA's own site, not from Bridge:

- DigiCert (the default TSA): the DigiCert root named as issuer, from DigiCert's published root certificates. Most
  operating systems already trust it: `-CAfile /etc/ssl/certs/ca-certificates.crt` (Debian/Ubuntu) or
  `-CApath /etc/ssl/certs` also works.
- FreeTSA (the fallback TSA): `cacert.pem` from freetsa.org.

The TSA's own certificate travels inside the token (Bridge asks for it), so `-untrusted` is not needed.

## 4. Check Bridge's signature

Bridge signs the ASCII text `bridge-manifest-v1:<content hash in lower-case hex>` (no trailing newline) with
Ed25519:

```bash
printf 'bridge-manifest-v1:%s' "$HASH" > message.txt
printf '%s' "$SIG" | openssl base64 -d -A > signature.bin
openssl pkeyutl -verify -pubin -inkey key.pem -rawin -in message.txt -sigfile signature.bin
```

Expected: `Signature Verified Successfully`. `-rawin` needs OpenSSL 3.0 or later. The same check in Python, with the
`cryptography` package:

```python
import base64
from cryptography.hazmat.primitives.serialization import load_pem_public_key

key = load_pem_public_key(open("key.pem", "rb").read())
key.verify(base64.b64decode(SIG), f"bridge-manifest-v1:{HASH}".encode("ascii"))  # raises InvalidSignature if bad
```

The RFC 3161 token does not depend on Bridge's key: even if that key were ever compromised, the token still fixes the
hash to its time.

## 5. Optional: the audit transparency roots

Every night Bridge verifies its append-only audit chains and publishes a signed Merkle root of the chain heads
(RFC 6962 hashing; `bridge/provenance/transparency.py` documents the leaf format):

```bash
curl -fsS "$HOST/api/transparency"
```

Each root is signed over `bridge-transparency-root-v1:<YYYY-MM-DD>:<merkle_root hex>`; check it exactly as in step 4
with that message. Keeping copies of these roots over time lets anyone detect a later rewrite of the audit history.

## Troubleshooting

- `Verification: FAILED ... message imprint mismatch`: the manifest file is not the registered one (edited, re-saved
  or a different version), or `$HASH` was mistyped.
- `unable to get local issuer certificate`: `tsa-root.pem` is not the root of the TSA that signed this token; print
  the token's certificates (step 3) and fetch the right root.
- `pkeyutl: Error ... -rawin`: OpenSSL is older than 3.0; use the Python check.
- `Signature Verification Failure`: wrong `key.pem` (match `kid` to `key_id`), a mistyped hash, or a newline in
  `message.txt` (use `printf`, not `echo`).

## Contacts

Questions about a certificate: the platform's support address. Disputes follow the platform's dispute process
(`docs/spec/06-feature-modules.md` 6.12); Bridge never rules on legal ownership.
