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
against Bridge directly, upload it at `https://<host>/verify`; the answer is match or no match.

From the command line, `POST /api/verify` takes the raw file as the body. Like every state-changing API call it needs
the CSRF double-submit pair: `GET /api/auth/csrf` returns a token and sets it as a cookie (`__Host-bridge_csrf` over
HTTPS), and the upload sends that cookie back together with the same token in the `X-CSRF-Token` header. Without
them the answer is `403` with the code `csrf_failed`.

```bash
curl -fsS -c cookies.txt -o csrf.json "$HOST/api/auth/csrf"         # {"csrf_token": "..."} and the cookie
TOKEN=$(sed -E 's/.*"csrf_token": *"([^"]+)".*/\1/' csrf.json)
curl -fsS -b cookies.txt -H "X-CSRF-Token: $TOKEN" -H 'Content-Type: application/octet-stream' \
  --data-binary @manifest.json "$HOST/api/verify?cert_id=$CERT"      # without ?cert_id= it searches every certificate
```

The answer holds `"match": true` or `false` and the SHA-256 Bridge computed (`content_hash`). Keep `cookies.txt` for
further uploads; the token is no secret of yours, it only shows the request came from the client that fetched it.

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

Both print `Verification: OK`. `openssl ts -verify` checks that the token's message imprint is this hash, that the
signature over the token holds, and that the signing certificate is a timestamping certificate chaining to
`tsa-root.pem`. `tsa-root.pem` is the root certificate of the TSA that issued the token (the last `issuer` printed
above), fetched from that TSA's own site, never from Bridge and never taken out of the token:

- DigiCert (the default TSA): the DigiCert root named as issuer, from DigiCert's published root certificates.
  Operating systems ship it too (`-CAfile /etc/ssl/certs/ca-certificates.crt` on Debian/Ubuntu works), but that
  trusts every CA in the store; the one root is the stricter check.
- FreeTSA (the fallback TSA): `cacert.pem` from freetsa.org.

The TSA's own certificate travels inside the token (Bridge asks for it with `certReq`); TSAs usually send their
intermediate CA too. If `openssl` reports `unable to get local issuer certificate` with the right root, save the
intermediate CA from the TSA's site as `tsa-intermediate.pem` and add `-untrusted tsa-intermediate.pem`: an
untrusted certificate only helps build the chain, the root still decides.

The token's nonce cannot be checked offline (only Bridge kept its request); Bridge checked it when it stored the token,
together with the rest of "What Bridge checks before it stores a token" below.

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

## What Bridge checks before it stores a token

A timestamp is evidence only if it comes from a TSA you trust and answers the question Bridge asked. The signature
alone proves neither: anyone can run a timestamp server and sign a plausible token. So the worker
(`bridge/provenance/tsa.py`) stores a token only when all of these hold, and otherwise tries the fallback TSA or
retries later (the record reads "Timestamp pending" meanwhile):

- it answers Bridge's own request: the message imprint is the SHA-256 content hash and the nonce is the random
  63-bit value Bridge sent with this request, so an older token (for this or any hash) cannot be replayed;
- its signing certificate chains, through the certificates in the token, to the CA bundle pinned for that TSA's URL
  (`TSA_CA_BUNDLE` for `TSA_URL`, `TSA_FALLBACK_CA_BUNDLE` for `TSA_FALLBACK_URL`). Every certificate on the chain
  is valid at the token's time, every issuer is a CA allowed to sign certificates and, when it states an extended
  key usage, to vouch for timestamping. Certificates in the token only fill in the chain; they are never trusted;
- the signing certificate has the timestamping usage as its only purpose, in a critical extension (RFC 3161), and is
  the certificate the signed ESS `signingCertificate(V2)` attribute names;
- the token's time is within 15 minutes of the worker's clock; for the hourly anchors of the audit chains, no more
  than one minute ahead of it, the bound the database applies to an anchor with its own clock.

## Operators: the pinned TSA bundles

Outside `APP_ENV` dev and test the worker refuses to timestamp without both bundles (`ConfigurationError` naming the
variable; the timestamp jobs retry and records stay "Timestamp pending" until it is fixed). Before staging, and
again before production, ops supply them:

1. Download each TSA's root certificate from the TSA's own site over HTTPS: DigiCert's root that issues its
   timestamping CA (the issuer chain of a current DigiCert token, step 3, names it), and FreeTSA's `cacert.pem`.
2. Check each file against a second source before trusting it: compare
   `openssl x509 -in <file> -noout -subject -fingerprint -sha256` with the fingerprint the TSA publishes (for
   DigiCert, also with the same root in the operating system's or Mozilla's trust store).
3. Put them on the worker as PEM files (they are public certificates, not secrets) and set `TSA_CA_BUNDLE` and
   `TSA_FALLBACK_CA_BUNDLE` to their paths. A bundle may hold several certificates (a root and its successor
   during a rollover); it may also pin the issuing CA itself. Each bundle checks only its own URL's tokens.
4. Prove the pair works before the release, from the worker host (a real TSA call, so never from tests or CI):

   ```bash
   printf 'bridge bundle check' > probe.txt
   openssl ts -query -data probe.txt -sha256 -cert -out probe.tsq
   curl -fsS -H 'Content-Type: application/timestamp-query' --data-binary @probe.tsq "$TSA_URL" -o probe.tsr
   openssl ts -verify -queryfile probe.tsq -in probe.tsr -CAfile "$TSA_CA_BUNDLE"
   ```

   `Verification: OK` (here `-queryfile` checks the nonce too). Repeat with `TSA_FALLBACK_URL` and its bundle.

When a TSA moves to a new root, its tokens stop verifying: records stay "Timestamp pending" and the failed timestamp
jobs name the chain failure (the timestamp step keeps retrying for two weeks). Add the new root to that TSA's bundle
(keep the old one while old tokens are still being checked), redeploy the worker, and the pending records are
timestamped on the next retry. In dev and test a TSA without a bundle is used without the chain check (logged as
`provenance.tsa_unpinned`); the tests pin a CA generated at test time.

## Troubleshooting

- `Verification: FAILED ... message imprint mismatch`: the manifest file is not the registered one (edited, re-saved
  or a different version), or `$HASH` was mistyped.
- `unable to get local issuer certificate`: `tsa-root.pem` is not the root of the TSA that signed this token, or the
  token lacks the intermediate CA; print the token's certificates (step 3), fetch the right root and, if needed, the
  intermediate for `-untrusted`.
- `pkeyutl: Error ... -rawin`: OpenSSL is older than 3.0; use the Python check.
- `Signature Verification Failure`: wrong `key.pem` (match `kid` to `key_id`), a mistyped hash, or a newline in
  `message.txt` (use `printf`, not `echo`).

## Contacts

Questions about a certificate: the platform's support address. Disputes follow the platform's dispute process
(`docs/spec/06-feature-modules.md` 6.12); Bridge never rules on legal ownership.
