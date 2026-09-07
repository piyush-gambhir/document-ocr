# Hosting Document OCR

Cloud Run is the simplest managed HTTP deployment. Lambda supports IAM-authenticated
function invocation and private S3 inputs. Cloudflare uses a Worker **and a Linux
container**; ordinary Python Workers do not run this native ONNX/OpenCV stack.
A Docker Compose preset runs the HTTP API on your own server with Caddy HTTPS.

All HTTP presets expose port 8000 internally and preserve `/health`, `/ready`,
`/documents`, `/scan`, `/scan/document`, `/scan/batch`, and `/review`. The deployed
API's `/documents` response describes its current capabilities. Persistent jobs
are opt-in for the server preset; cloud presets do not enable a local job store.

## Shared configuration

| Input | Default | Meaning |
|---|---|---|
| `DOCUMENT_OCR_NAME` | `document-ocr` | Service/stack name |
| `DOCUMENT_OCR_KYC_LANGS` | `en` | Up to four of `en,latin,devanagari,ka,ta,te` |
| `DOCUMENT_OCR_PROFILE` | `economy` | `economy` or `warm` |
| `IMAGE_URI` | build source | Optional provider-compatible prebuilt image |

The profile changes Cloud Run minimum instances and Cloudflare idle time. Lambda
and the continuously running server preset retain their declared resource settings.

Images install `requirements.lock` and run `python -m core.model_setup` at build
time. Set the language list **before building**. When using a prebuilt image,
its bundled models must match the configured languages. Images should be pinned
by digest for repeatable production releases. The HTTP and Lambda entrypoints
use separate images, sharing the same core Python implementation.

`.dockerignore` and `.gcloudignore` allow only required source into builds. They
exclude local virtual environments, npm dependencies, credentials, and private
identity-document fixtures. Keep these files when copying deployment templates.

## Google Cloud Run

Prerequisites: a billed Google Cloud project, `gcloud`, Python 3, authenticated CLI
credentials, and permission to enable services/create service accounts, builds,
repositories and Cloud Run services. Local Docker is not required.

```bash
export GCP_PROJECT=your-project
export GCP_REGION=asia-south1
export GCP_INVOKER_MEMBER=serviceAccount:caller@your-project.iam.gserviceaccount.com
export DOCUMENT_OCR_KYC_LANGS=en
bash deploy/cloudrun/deploy.sh
```

The wrapper enables APIs, creates the image repository and runtime identity as
needed, builds remotely for Linux/amd64, then deploys the definition produced by
`deploy/cloudrun/render_service.py`. Both deployment and build use this one
configuration path. Existing public invoker bindings are removed before updating
an existing service; IAM failures stop deployment. No public invocation is enabled.

Optional inputs:

- `GCP_AR_REPO`: Artifact Registry repository name.
- `DOCUMENT_OCR_SERVICE_ACCOUNT`: existing runtime service-account email.
- `GCP_API_TOKEN_SECRET`: existing Secret Manager secret ID containing an optional
  application Bearer token. `GCP_API_TOKEN_VERSION` defaults to `latest`.
- `DOCUMENT_OCR_MAX_INSTANCES`: scale-out cap, default 10.
- `DOCUMENT_OCR_PROFILE=warm`: maintain one instance; economy allows scale to zero.

The initial sizing is two vCPUs, 2 GiB memory, concurrency one, and startup CPU
boost. OCR work is serialized within each process. Benchmark before changing
concurrency or reducing memory. A warm profile has ongoing idle-instance cost.

The endpoint requires a Google-signed ID token whose audience is the service URL.
A static application API token cannot satisfy Cloud Run IAM. For local inspection:

```bash
gcloud run services proxy document-ocr --project "$GCP_PROJECT" --region "$GCP_REGION"
```

For application calls, use the SDK's asynchronous header provider with a Google
auth library. Put Google's token in `X-Serverless-Authorization` when the app also
uses `Authorization` for its own `API_TOKEN`. Do not store a short-lived Google
ID token as a permanent API key. See [Google service authentication](https://docs.cloud.google.com/run/docs/authenticating/service-to-service).

## AWS Lambda

Prerequisites: AWS CLI credentials, AWS SAM CLI, Docker with Linux/amd64 support,
and permission to create the CloudFormation stack, Lambda role and image repo.

```bash
export AWS_REGION=ap-south-1
export AWS_STACK_NAME=document-ocr
export DOCUMENT_OCR_KYC_LANGS=en
bash deploy/lambda/deploy.sh
```

The SAM template fixes the Dockerfile path relative to the repository build
context. It creates an x86_64 image function with 2 GiB memory, 120-second timeout,
and a bounded concurrency of 10. The printed function name works with SDK
`mode: 'lambda'`. Callers need `lambda:InvokeFunction` permission. The execution
role and caller role are separate; no public Function URL is created.

To read larger documents from an existing private S3 bucket:

```bash
export DOCUMENT_OCR_S3_BUCKET=your-private-documents
export DOCUMENT_OCR_S3_PREFIX=uploads/
bash deploy/lambda/deploy.sh
```

The role grants `s3:GetObject` only within that prefix; it cannot list, upload or
delete objects. Upload from your application using its own appropriate identity.
For SSE-KMS objects, separately grant the runtime role decrypt permission on the
specific KMS key. Direct synchronous invocation has a 6 MiB request limit, leaving
approximately 4.5 MiB for raw bytes when encoded as base64; use S3 for larger
inputs. [AWS limits](https://docs.aws.amazon.com/lambda/latest/dg/gettingstarted-limits.html)

`IMAGE_URI` may reference an already-built Lambda-compatible image in ECR in the
same region. It must target one architecture. Runtime writes must use `/tmp`;
models are bundled to avoid runtime downloads. The HTTP Docker image alone is
not a Lambda runtime. [Lambda image requirements](https://docs.aws.amazon.com/lambda/latest/dg/images-create.html)

AWS Lambda Web Adapter is another valid architecture for exposing the same
FastAPI service through a Function URL/API Gateway, but this preset intentionally
retains the existing direct-invoke handler and its S3 contract. The adapter is not
required or installed here. [Official Web Adapter](https://github.com/aws/aws-lambda-web-adapter)

## Cloudflare Worker and Container

Prerequisites: a Workers Paid plan, Node.js 20+, Docker with Buildx, and Wrangler
credentials. The Worker authenticates document requests before selecting a container; the
container runs native Python on Linux/amd64. Plain Python Workers are not an
interchangeable target. [Container setup](https://developers.cloudflare.com/containers/get-started/)

```bash
npm ci --prefix deploy/cloudflare --ignore-scripts
cd deploy/cloudflare
npx wrangler login
npx wrangler secret put API_TOKEN
npm run deploy
```

The secret command prompts for the value; it is not stored in source. For a custom
`DOCUMENT_OCR_NAME`, pass that same name with `wrangler secret put API_TOKEN --name
YOUR_NAME`. Required-secret validation prevents unauthenticated deployment. For
local development, place the token in an ignored `.dev.vars` and use `npm run dev`.
Alternatively, supply `API_TOKEN` in the environment when running the deployment
wrapper. It passes the secret through a temporary private file and removes that
file on exit; no secret value is placed in command-line arguments.

The deployment wrapper consumes the shared configuration variables. Set
`DOCUMENT_OCR_MAX_INSTANCES` to select a fixed routing pool (default two). The
preset uses `standard-2` instances. `economy` sleeps idle containers after ten
minutes; `warm` extends that to one hour, and does **not** promise a permanently
warm instance. Built-in demand-based container autoscaling is not assumed.
[Scaling and routing](https://developers.cloudflare.com/containers/configuration/scaling-and-routing/)

Outbound internet access in the OCR container is disabled; all selected models
must exist in the image. Uploads/responses stream through the Worker and successful
and partial responses use `Cache-Control: no-store`. Document routes and
health/readiness probes require the Bearer token. `GET /review` serves the public
static review screen so a browser can load its token-entry form; document data
still requires authentication.

```bash
npm run types
npm run typecheck
npm test
npm run check        # Worker/config dry-run; does not build or deploy containers
npm run check:image  # also builds the image locally; requires Buildx and disk space
```

The generated `worker-configuration.d.ts` is produced by Wrangler, not handwritten.
Wrangler owns the Worker/container and Durable Object migrations. Avoid managing
the same Worker concurrently with Terraform; Terraform can separately own DNS or
Access resources.

## Your own server with HTTPS

Prerequisites: Docker Compose on the target server, a DNS name pointing to it,
and ports 80/443 reachable for Caddy certificates and HTTPS. Run the command on
that server, or use an existing Docker remote context.

```bash
export DOMAIN=ocr.example.com
export API_TOKEN='replace-with-a-random-private-token'
bash deploy/server/deploy.sh
```

Supply real secrets through your shell or a private environment file. Caddy keeps
certificates in named volumes. The OCR container is reachable only on the Compose
network; Caddy exposes HTTPS. `IMAGE_URI` avoids building on the server. To stop
without deleting volumes:

```bash
docker compose -p document-ocr -f deploy/server/compose.yaml down
```

### Optional encrypted persistent jobs

The ordinary HTTP preset has jobs disabled. To enable them, generate a Fernet key
using the installed Python dependencies, retain it securely, and start the jobs
overlay:

```bash
export DOCUMENT_OCR_JOB_KEY="$(python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')"
export DOCUMENT_OCR_JOBS_ENABLED=true
bash deploy/server/deploy.sh
```

The API and a separate `python -m core.jobs worker` process share the `ocr_jobs`
volume and key. Preserve both across upgrades. Losing the key makes retained data
unreadable; do not generate a new key on every restart. Back up encrypted storage
and its key separately. Cloud Run, Lambda and Cloudflare presets do not claim
persistent job support from ephemeral container filesystems.

Retention defaults to 24 hours; set `DOCUMENT_OCR_JOB_RETENTION_SECONDS` to a
value from 60 to 604800. Optional completion notifications use one operator-owned
HTTPS endpoint: set `DOCUMENT_OCR_WEBHOOK_URL` and a
`DOCUMENT_OCR_WEBHOOK_SECRET` of at least 32 characters, then enqueue with
`notify: true`. The API and worker both receive these settings. Notifications
contain only the job ID/status, with a timestamp and HMAC-SHA256 signature;
receivers must validate the signature and deduplicate `X-Document-OCR-Event`.

## Terraform

`infra/cloudrun` and `infra/lambda` are independent Terraform roots. Copy the
relevant `terraform.tfvars.example` to a private `terraform.tfvars`, supplying a
prebuilt image URI and provider/project configuration:

```bash
terraform -chdir=infra/cloudrun init
terraform -chdir=infra/cloudrun plan
terraform -chdir=infra/cloudrun apply
```

Use `infra/lambda` for AWS. Each root creates a repository for future image builds,
a runtime role/service identity and the service/function. The first `image_uri`
must already exist in a suitable registry; Terraform does not build images. If
you already used a wrapper to create resources of these names, import them into
Terraform or choose a different name. Do not let two deployment systems own the
same resources. Provider versions are recorded in `.terraform.lock.hcl`.

Cloud Run accepts only named IAM invokers and references an existing optional
Secret Manager secret. Lambda accepts an optional input bucket/prefix and grants
only prefix-scoped reads. Secret contents are never Terraform variables. Choose
a protected remote state backend before team use; templates deliberately do not
hardcode an account-specific backend.

Validate without applying:

```bash
terraform -chdir=infra/cloudrun init -backend=false
terraform -chdir=infra/cloudrun validate
terraform -chdir=infra/lambda init -backend=false
terraform -chdir=infra/lambda validate
sam validate --template-file deploy/lambda/template.yaml --lint
```

## Verification before production

After deployment, check `/ready`, make an authenticated scan with a synthetic
fixture, confirm missing/wrong credentials are rejected, and measure cold-start
latency and peak memory for your enabled languages. Never upload real identity
documents as test fixtures to public services. Image builds, platform IAM and live
endpoint behavior require verification in your own cloud account; a configuration
or Terraform validation alone does not establish a working cloud deployment.
