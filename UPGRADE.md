# Node 26 upgrade verification

Reviewed on 25 October 2026 against the previous `v3.1.2` source. The shared
[upgrade playbook](https://github.com/piyush-gambhir/pdf-everything/blob/main/docs/upgrade-playbook.md)
describes the review and release sequence.

## Changes

- Node 26.12.1 is pinned locally and in SDK, gateway, and publishing CI.
- SDK release 3.1.3 retains the SDK's existing Node 18 runtime requirement.
  Development and deployment tooling use Node 26. Python still requires 3.14.
  The Python package and server remain at 3.1.2. Application source and inference
  dependencies are unchanged.
- SDK checks use TypeScript 7.0.2. `tsup` declaration generation keeps the
  TypeScript 6.0.3 compiler API, with a separate compatibility check in CI.
  Both checks must pass because the native compiler and API consumers can
  disagree on supported syntax and declarations.
- AWS SDK, tsup, Vitest, Wrangler, and Node types are updated. Publishing uses
  `npm ci` to honor the reviewed lockfile.
- Wrangler's development dependency graph overrides Undici within version 7
  to include the fixes in 7.30.1. The upstream
  [security advisory](https://github.com/advisories/GHSA-xjj6-f33q-929c)
  describes the affected HTTP client behavior.
- Setup documentation covers npm's dependency install-script approval for the
  bundled Python runtime. HTTP and Lambda clients can skip local Python setup.

## Verification

- Fresh `npm ci` succeeds for both independent lockfiles.
- SDK TypeScript 7 and TypeScript 6 checks pass. ESM, CommonJS, and declaration
  builds pass, with 82 SDK tests and the browser privacy regression test.
- Gateway typecheck, 12 tests, and Wrangler's deployment dry-run pass.
- The Python suite passes under Python 3.14.6: 847 passed, two skipped.
- Real synthetic PAN, passport, and W-9 images pass OCR field checks.
- A separate consumer installs the packed npm artifact. Its ESM and CommonJS
  imports work. Its HTTP client verifies real OCR output for all three samples,
  authenticated catalog access, rejection without credentials, and invalid
  input rejection. Local mode also starts the bundled Python runtime and
  extracts the expected PAN fields after install-script approval.
- The Linux/amd64 server image builds. The packed SDK passes the same HTTP
  checks against that image with a read-only root filesystem and writable
  `/tmp`. This runs under emulation on an arm64 development host.
- Full and production npm dependency audits are clear for both manifests.
  Audits cover known dependency advisories, not the entire application's
  security. TypeScript 6 is the SDK's documented direct-dependency holdback.

Existing tests exercise extraction, validation, authentication, retries, privacy,
and failure recovery. None was removed solely because it predates this upgrade.

## Reproduce

Use the Node version in `.nvmrc`. Install both independent npm workspaces:

```bash
PASSPORT_OCR_SKIP_PYTHON=1 npm ci --prefix packages/passport-ocr
npm ci --prefix deploy/cloudflare
npm run typecheck --prefix packages/passport-ocr
npm run typecheck:compat --prefix packages/passport-ocr
npm test --prefix packages/passport-ocr
node --test tests/javascript/review.test.cjs
npm run typecheck --prefix deploy/cloudflare
npm test --prefix deploy/cloudflare
npm run check --prefix deploy/cloudflare
npm run build --prefix packages/passport-ocr
npm pack ./packages/passport-ocr --dry-run
npm audit --prefix packages/passport-ocr
npm audit --prefix deploy/cloudflare
uv run --no-sync pytest tests/python
uv run --no-sync python scripts/ocr_smoke.py
docker build --platform linux/amd64 -f deploy/docker/Dockerfile -t document-ocr:review .
```

Run the existing Python installation steps in `CONTRIBUTING.md` before the
Python commands. Synthetic samples prove selected behavior, not population
accuracy. This upgrade changes the Node SDK and toolchain; it does not change
the locked Python/ONNX inference dependencies or establish an OCR speedup.

## Publication

Passing builds and a release tag do not prove publication. Check the Publish
workflow, the GHCR image source revision and digest, and the npm registry entry
before marking a release complete. npm publication is opt-in via `PUBLISH_NPM`
and requires publisher authentication. The Lambda image also downloads its
Python base from AWS Public ECR, which can limit anonymous shared runners.
An actual AWS Lambda invocation and a Cloudflare deployment are separate checks.
