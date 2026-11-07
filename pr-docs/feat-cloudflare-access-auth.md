# Pull Request #5485: Cloudflare Access Zero-Trust Authentication

* **PR Link**: **[https://github.com/Niko1221/Strata/pull/5485](https://github.com/Niko1221/Strata/pull/5485)**
* **Status**: **Open**
* **Title**: `[Engine] serve: Cloudflare Access zero-trust JWT authentication (STRATA_CF_ACCESS_TEAM)`
* **Area**: `[Engine]`
* **Target Repo**: `Niko1221/Strata:main`
* **Source Branch**: `DamirLukina88:D.L.-AI---Strata:feat/cloudflare-access-auth`
* **Head Commit**: `58be0d3d` (Pushed follow-up addressing all 3 Copilot review points: CSRF origin check on Access claims, certificate fetch failure throttling, and non-dict header validation)
* **Review Follow-up Comment**: [https://github.com/Niko1221/Strata/pull/5485#issuecomment-6707159351](https://github.com/Niko1221/Strata/pull/5485#issuecomment-6707159351)
* **Tests**: 11/11 unit tests passing in `serve.test_cf_access`, 30/30 security tests passing in `serve.test_security`

---

## Pull Request Body

```markdown
## Problem and result

When exposing Strata remotely through a tunnel (such as cloudflared), clients connecting through a Cloudflare Access application must currently enter and store the server API key in browser storage, which presents credential leakage risks on shared machines.

This change adds opt-in support for verifying Cloudflare Access JWT assertions (`Cf-Access-Jwt-Assertion` header and `CF_Authorization` cookie). When configured via `STRATA_CF_ACCESS_TEAM` and `STRATA_CF_ACCESS_AUD`, requests arriving over loopback from the local tunnel connector are authorized without requiring an API key.

## Related discussion

Refs #4207 (remote host access and tunnel overrides).

## Approach

- Added `serve/cf_access.py`: A standard-library-only RSA PKCS#1 v1.5 SHA-256 JWT verifier (zero external dependencies). Verifies signatures against Cloudflare published JWKs (`https://<team>.cloudflareaccess.com/cdn-cgi/access/certs`, cached for 1 hour with a 60-second minimum refetch interval on both unknown `kid` lookups and failed network refreshes).
- Validates that the decoded JWT header and payload are JSON objects, and checks the token issuer, audience tags, and timestamp validity (`exp`, `nbf` with 60-second clock skew tolerance).
- When only `STRATA_CF_ACCESS_TEAM` is set, the server operates in discovery mode: it logs the AUD tag of the first valid login seen without authorizing, allowing the audience tag to be copied easily from logs.
- `serve/server.py`: In `_authorized()` and `_authorized_telemetry()`, checks `_access_claims()` if `self.cf_access` is active and the client address is loopback (`127.0.0.1` / `::1`).
- Preserves CSRF protection in `_foreign_page()`: browser POSTs authenticated via ambient Cloudflare Access credentials (rather than an explicit API key via `_given_key()`) still must pass `Origin` and `Content-Type: application/json` checks.
- If unconfigured, `self.cf_access` is `None` and the default authentication path remains byte-identical.
- Unit tests added in `serve/test_cf_access.py` (covering JWT verification, non-dict header rejection, failed fetch retry throttling, CSRF `Origin` enforcement on Access cookies, and end-to-end HTTP mock server authorization).
- Documentation updated in `docs/DETAILS.md`.

## Validation

**Passed:**
- `python3 serve/test_cf_access.py -v`: All 11 unit tests passed in 1.80s (key caching, tamper rejection, non-dict header rejection, failed fetch retry throttling, expiry checks, discovery mode, token extraction, CSRF `Origin` check with Access cookies, and live HTTP mock server auth). Tested on revision 58be0d3d.
- `python3 -m unittest serve.test_security -v`: All 30 security and auth tests passed in 10.3s.
- `python3 tools/test_source_nul_bytes.py`: Passed (0.16s).
- Tested live on Linux host (CachyOS, kernel 6.13) behind a Cloudflare tunnel connector.

**Failed:**
- None.

**Not run:**
- Non-Linux platforms (the implementation is pure Python standard library and OS-independent).

## Limits

- Only requests originating from loopback (`127.0.0.1`, `::1`, `::ffff:127.0.0.1`) are eligible for Access claim authorization to prevent spoofing if the port is exposed directly.
- Only RS256 algorithm is supported (Cloudflare Access default).
```
