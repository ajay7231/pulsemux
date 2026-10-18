# PulseMux clinical voice platform

This is the first working management platform around the existing voice simulator.
It provides persistent hospital workspaces, role-based access, encrypted provider
connections, versioned agents, reviewed knowledge, contacts, campaigns, and call
history. The browser and Twilio transports use the same managed agent runtime.

## Run locally

```sh
worker-py/.venv/bin/python -m pip install -r worker-py/requirements.txt
make platform
```

Open http://localhost:8001/dashboard/ and create the initial administrator and
hospital workspace. Select your hospital timezone from the dropdown of all
server-supported IANA timezones. The same selector appears in workspace settings
and contact forms. The first-run form is available only until setup succeeds.
Returning users can choose **Already have a workspace? Sign in**, or open
http://localhost:8001/dashboard/login directly, and use their registered email
and password. Accounts belong to the database connected to this server.
No default user or password is installed. No sample patients or credentials are
seeded into your workspace.

Local data is stored in `worker-py/data/platform.db`. A generated Fernet key is
stored separately in `worker-py/data/secret.key` with mode 0600. Both are ignored
by Git. Keep the key: a database backup without the key cannot decrypt provider
connections. Local development defaults to SQLite unless `DATABASE_URL` is set;
deployment uses PostgreSQL.

### Local PostgreSQL in Docker

`make postgres-up` starts PostgreSQL 17 with pgvector on `127.0.0.1:5433`, using
persistent volume `pulsemux-local_postgres-data`. It generates a private random
password in ignored `worker-py/data/postgres.env` on first use. It starts only the
database. `make postgres-down` stops it while retaining the volume.

Set `DATABASE_URL` in the root `.env` to
`postgresql+psycopg://pulsemux:YOUR_GENERATED_PASSWORD@127.0.0.1:5433/pulsemux`
and restart `make platform`. Keep that env file private and out of Git. The
current local installation is configured this way. Switching databases does not
automatically migrate accounts: back up and transfer existing data first. The
previous local SQLite database is retained, with a consistent backup at
`worker-py/data/platform-before-postgres.db`.

Back up the PostgreSQL volume and `worker-py/data/secret.key` together. The
standalone local database and full deployment stack use separate volumes; the
full deployment configuration is described below.

The local server binds to loopback. To work on the frontend separately, run:

```sh
npm --prefix dashboard ci
npm --prefix dashboard run dev
```

Vite proxies `/api`, `/ws`, `/simulator`, and `/static` to port 8001. For this
separate-port development setup, use the backend-served dashboard for login and
voice tests: the application intentionally enforces same-origin sessions.

For scheduled local campaigns, run another terminal:

```sh
make platform-worker
```

`make studio` / `make ui` also start the backend (default port 8000), but the root
now redirects to the dashboard. Build its assets first with `make dashboard-build`.
The simulator is at `/simulator?agent=AGENT_ID&draft=1` and requires a workspace
session. Legacy command-line benchmark scripts remain available.

## First agent

1. **Connections:** add Deepgram or Groq for ASR and Groq or OpenAI for the LLM.
   Deepgram Aura-2 TTS uses a saved Deepgram connection; Kokoro runs locally when
   its model files are available. Connection testing makes an authenticated,
   read-only provider request. It does not prove every model is available.
2. **Knowledge:** create a collection, add text or upload a PDF/TXT/Markdown/CSV,
   and have an administrator approve it. PDF extraction is text-only: scanned
   documents need external OCR. Original uploaded files are not retained.
3. **Agents:** choose one of eight workflow templates, edit behavior, select
   connections/models/voice, attach collections, and enable permitted actions.
   Voice & models explains missing credentials and offers **Add connection** in
   place, preserving the agent draft and selecting the newly saved connection.
   The language model dropdown loads the selected account's compatible text
   models from the [Groq models API](https://console.groq.com/docs/models) or
   [OpenAI models API](https://platform.openai.com/docs/api-reference/models).
   It supports retrying failed requests and flags unavailable saved models.
   Changing accounts clears the previous model. Testing checks the saved
   configuration and current model availability before opening the simulator.
   The catalog intentionally includes only model families supported by this
   runtime's chat-completions parameters; audio, embedding, moderation, and
   unsupported reasoning/Responses-only models are excluded.
4. **Save draft**, then **Test agent**. Testing opens within the dashboard, with
   call controls, a live transcript, background noise reduction, and call metrics.
   It uses the saved draft's provider and voice settings. **Back to agent** or
   navigating away ends the call and releases microphone access. Complete at
   least one patient turn with an assistant response. Test conversations are
   saved in Call history.
5. **Publish agent**. Only administrators can publish. A publication pins its
   configuration and approved knowledge snapshot. Knowledge changes after a test
   require another test before publication. Editing a draft does not change
   active calls or an existing published version.

Agent templates cover inbound reception, appointment reminders, booking requests,
procedure preparation, discharge follow-up, preventive-care recalls, medication
reminders, and feedback. They are starting points requiring hospital review.

Instructions support `{{hospital_name}}`, `{{patient_name}}`, and additional contact
variables such as `{{appointment_date}}`, `{{appointment_time}}`, and
`{{doctor_name}}`. Missing values are marked `[not provided]`, never fabricated.

### Actions in this release

Actions are permission-checked, recorded, and deliberately restricted to clear
caller commands. The agent explains the available phrases:

- "Call me back" creates a staff task.
- "Transfer me to staff" transfers a telephone call to the configured number.
- "Confirm my appointment" records attendance intent for reminder agents.
- "Reschedule my appointment" / "Cancel my appointment" creates a scheduling task.
- "Stop calling me" updates the matched contact's opt-out preference. If the call
  has no matched contact, it creates a staff-review request instead.
- "End the call, please" ends after farewell playback.

These actions do **not** modify an EHR or scheduling system. An actual appointment
change still requires staff confirmation. Phone matching is not patient identity
verification; an authenticated patient-verification workflow is required before
connecting tools that read or change clinical records. Agents should not be
configured to give diagnoses or alter medication instructions.

## Knowledge retrieval

Keyword retrieval works without an embedding service. To enable semantic search,
select an OpenAI connection when creating a collection, upload a document, and
click **Index semantic**. This explicitly sends extracted text to OpenAI and
incurs provider usage. Embeddings use `text-embedding-3-small` (1536 dimensions),
are stored in pgvector columns in PostgreSQL, and are combined with keyword
matches by reciprocal-rank fusion. SQLite stores the vectors as JSON for local
parity. Publication snapshots preserve sources; call events list the sources
used for each response. Query embeddings are computed only for semantically
indexed collections. Provider failure falls back to keyword retrieval.

The first implementation ranks the pinned snapshot in the worker to keep call
versions reproducible. It does not yet use a global approximate-nearest-neighbor
index; keep collections focused by department. Attached extracted text is capped
at 500,000 characters. Uploads are limited to 5 MB, PDFs to 100 pages, and document
text to 200,000 characters. Archiving a document pauses agents whose current
published version references it; older campaign versions are checked again
before calls are placed. Expired documents cannot be used for new calls.

## Twilio setup

Telephone calls require an owned Twilio number and a public HTTPS origin with a
valid certificate. Set `PUBLIC_BASE_URL` to the origin, without a path, query, or
trailing route. The same origin must reach HTTP and WebSocket endpoints.

1. Save a Twilio connection with Account SID and Auth Token. Optionally provide
   an API key SID/secret for API calls. The Auth Token is still required to validate
   incoming signatures.
2. Assign the number in **Phone numbers** and select the inbound agent.
3. In Twilio Console, configure the number's incoming-call webhook to HTTP POST:
   `https://YOUR_ORIGIN/api/twilio/CONNECTION_ID/inbound`.
4. Add a synthetic test contact with explicit calling permission and use
   **Call history → Place a call** for an outbound test.

Inbound and outbound calls create `<Connect><Stream>` TwiML pointing to the shared
runtime. Both HTTP callbacks and WebSocket handshakes are signature-validated.
Each stream also needs a one-time token tied to the persisted call and Twilio SID.
ASR is currently utterance-based with automatic VAD segmentation, as in the
simulator; audio frames and agent responses stream continuously. This is not a
sub-500ms latency guarantee.

Phone playback uses 20ms G.711 mu-law frames. Interruption clears queued media;
a farewell waits for Twilio's playback `mark` before hanging up. A missing phone
TTS response creates a staff task and ends the call instead of pretending browser
speech synthesis is available. Duration and inactivity limits bound sessions.

In platform mode, the Go gateway (`VOICE_RUNTIME_URL=http://platform:8000`)
forwards HTTP and WebSocket traffic to the shared runtime. It does not use the
older placeholder gRPC implementation. Without this variable, its standalone
transport console retains its original behavior. Terminate TLS in front of the
platform or Go gateway; neither test port is an internet-facing TLS endpoint.

No live phone calls are placed during the automated tests. Campaign dispatch is a separate process; starting the dashboard alone does not start a scheduler.

## Campaigns and contacts

Contacts use E.164 phone numbers, explicit consent, opt-out state, timezone, and
agent variables. CSV imports are previewed before writing. Required headers are
`name,phone`; optional headers are `consent,opted_out,timezone`. Extra columns are
agent variables. Missing consent defaults to false. Duplicate saved numbers are
skipped. Invalid rows must be fixed before import.

Campaigns pin a published agent version and store recipients in PostgreSQL. Set a
start time, calling window, concurrency cap, maximum attempts, and retry delay.
Each contact's timezone determines its calling window. Consent, opt-out, agent
status, and current knowledge approval are rechecked before dispatch.

Pausing prevents new calls and leaves active calls alone. Busy/unanswered calls
may be retried within limits. Failed calls are surfaced for review. Provider
callbacks are deduplicated and cannot move a terminal call back to ringing.

The database stores dispatch intent before the external request. An uncertain
request or a worker crash during dispatch is **not** automatically redialed:
review the staff task and Twilio call log before manually scheduling another
attempt. This avoids assuming the external provider supports exactly-once calls.
Run a single Celery beat scheduler; multiple worker processes are supported.

## Deployment

Use the separate deployment file; the original transport-development Compose
stack is retained:

```sh
# Populate a private env file from .env.example.
# Set a random hexadecimal POSTGRES_PASSWORD and random PLATFORM_SETUP_TOKEN.
# Generate PLATFORM_ENCRYPTION_KEYS using Fernet.generate_key().
# Set PUBLIC_BASE_URL to the real HTTPS origin.
docker compose --env-file YOUR_PRIVATE_ENV_FILE -f deploy/platform-compose.yml up --build -d
```

This starts PostgreSQL/pgvector, Redis, the application, the Go ingress proxy, a
Celery worker, and one scheduler. The platform binds host port 8001 and the Go
proxy binds 8080, both on loopback for a TLS reverse proxy. Do not expose the
original development Grafana or Redis ports as part of a hospital deployment.
First setup in production additionally requires the server's setup token.

The application image builds the React dashboard and runs as an unprivileged
user. Alembic runs before application startup. Runtime images do not contain
`.env` files or local workspace data. `GET /readyz` checks database access and
credential encryption configuration. Do not put patient information in process
logs, deployment environment names, or metrics labels.

Provider keys for managed agents are loaded from workspace connections, never
from the legacy global `.env` keys. Credential revocation blocks new runtime
resolution. Rotation replaces a credential for future provider requests.
`PLATFORM_ENCRYPTION_KEYS` accepts comma-separated Fernet keys, newest first,
allowing old ciphertext to be read while connection credentials are rotated.
Do not remove an old encryption key before all connection records have been
re-encrypted by rotation.

### HTTPS edge and production policy

Set `PUBLIC_BASE_URL` to a real HTTPS origin with DNS pointing to the deployment.
The optional `edge` profile starts Caddy on ports 80/443 and obtains its TLS
certificate. To start the web-facing services without enabling campaign dispatch:

```sh
docker compose --env-file YOUR_PRIVATE_ENV_FILE -f deploy/platform-compose.yml --profile edge up --build -d edge
```

This starts the edge's gateway, application, PostgreSQL and Redis dependencies;
it does not start the scheduler or campaign worker. The full-stack command above
also starts those outbound-capable services and should be used intentionally.
Certificate issuance requires working DNS and inbound ports 80/443. This profile
has been configured but is not enabled by the local development server.

Production requires an HTTPS origin, encryption keys and a Redis URL. The server
rejects unexpected Host headers and non-HTTPS application traffic. The internal
readiness endpoint remains available to the container health check. The image
trusts forwarded scheme/IP headers only because its backend ports are private or
loopback-bound behind the included ingress: do not expose the backend directly.
If using a different ingress, configure its forwarded-header trust boundary
before exposing it.

API responses and dashboard HTML use `Cache-Control: no-store`; versioned assets
use immutable caching. The dashboard has CSP, anti-framing, MIME-sniffing,
referrer and microphone/camera policies. Login limits are shared through Redis
per IP and normalized account identifier; production fails closed if that limit
cannot be applied. Keep Redis on the internal service network.

### Sessions and account offboarding

The dashboard restores its server session, handles expired authorization
centrally, synchronizes login/logout between tabs, and clears account-bound
queries and drafts on sign-out. Network failures during session restoration show
an explicit recovery screen rather than a misleading login failure. A sign-out
whose server result is uncertain is reported as such.

Administrators can deactivate another user or revoke all of a user's sessions
from Settings. The API prevents self-deactivation and preserves an active
administrator. These actions are scoped to the current workspace and audited.
HTTP authorization is checked on every request; browser voice sockets re-check
session and role validity at least once a second and before every new call.

### Routed and paginated dashboard

Pages have URLs under `/dashboard/`, including `/dashboard/agents/:agentId` and
`/dashboard/agents/:agentId/simulate`. Direct navigation and refresh use the SPA
fallback; unknown pages have a recovery screen. Agent edits prompt before
navigation discards unsaved work. Viewers cannot enter creation or simulator
routes, and backend authorization remains authoritative.

The dashboard uses `/api/resources/{resource}` for bounded lists. Parameters are
`page`, `page_size` (maximum 100), `q`, `sort` and `direction`; responses contain
`items`, `total`, `page`, `page_size` and `pages`. Search is scoped to explicit
fields on the server. Campaign lists return grouped recipient counts rather
than every recipient. Older list endpoints remain for compatibility; new clients
should use the resource endpoints. The audit dialog is paginated too.

Query data is scoped to the workspace, cached only in memory, cancelled when no
longer needed, and invalidated by the affected resource after changes. Read
failures have bounded backoff; mutations are never retried automatically. A
mutation timeout tells the operator to inspect the record before resubmitting.

### Access and data handling

- Administrators manage credentials, team access, knowledge approval, and publishing.
- Operators manage drafts, contacts, campaigns, calls, and staff tasks.
- Viewers can inspect records but cannot start voice sessions or modify state.
- Sessions are HttpOnly, SameSite Strict, and Secure in production; unsafe
  requests and browser WebSockets are checked for same-origin access.
- Every management query and runtime lookup is scoped to the workspace.
  PostgreSQL row-level security and external SSO/MFA are not implemented yet;
  use dedicated hospital deployments while those additional boundaries are built.
- No audio recordings are stored. Transcripts, source references, outcomes, and
  tool events are persisted. A scheduled retention job deletes expired call
  events and clears patient-bearing call snapshots and staff-task details.
  Aggregate call records and audit events remain. Contacts and approved knowledge
  have their own operational lifecycle and are not deleted by call retention.
- Login throttling is process-local; deploy an additional proxy-level limiter.
- Infrastructure disk encryption, backups, provider agreements, regional data
  handling, clinical review, and an operational incident process must be assessed
  before handling real patient information. This code is not a compliance certification.

### Backup and restore

Back up PostgreSQL, the external encryption key, and any local Kokoro model assets.
Store database backups and the key in separately controlled locations. Example:

```sh
docker compose --env-file YOUR_PRIVATE_ENV_FILE -f deploy/platform-compose.yml exec -T postgres pg_dump -U pulsemux pulsemux > BACKUP.sql
```

Restore into an empty database, restore the same encryption key, run
`alembic upgrade head`, and verify login, connection decryption, agent versions,
and a synthetic simulator call before routing telephone traffic. Test restoration
regularly. `platform-down` preserves named volumes; no volume-removal command is
part of the normal shutdown workflow.

## Validation

```sh
make platform-test
# Optional focused commands:
worker-py/.venv/bin/python -B -m unittest discover -s worker-py/tests
node --test worker-py/tests/call.test.cjs
npm --prefix dashboard test
cd gateway-go && go test ./...
```

Tests use disposable databases and mocked provider requests. Live speech quality,
actual carrier behavior, transfer destinations, and hospital procedures still
need a controlled end-to-end acceptance call before a pilot.

## Scope for the next release

The platform is usable for configuring and testing agents and piloting operational
outreach with staff handoff. It is not the full hospital integration roadmap.
Remaining work includes an authenticated scheduling/EHR adapter, durable external
file/recording storage if enabled, SSO/MFA, database row-security policies,
multilingual prompts and voices, structured free-form tool calling, scale tests,
and a hospital-reviewed clinical acceptance suite. The existing keyword red-flag
heuristic is not a validated triage system. A project license should be chosen
before publishing an open-source release.


### P2/P3 operations and diagnostics

Production application startup verifies that the database Alembic revision matches
all migration heads. It does not create extensions, tables, or indexes. Run
`alembic -c worker-py/alembic.ini upgrade head` from the repository root before
starting a directly managed backend. The container command runs Alembic before Uvicorn;
for a deployment with separate migration and runtime database roles, run Alembic as
a migration job, then override the runtime command to start Uvicorn directly. The
migration role requires DDL privileges; the runtime role can use narrower privileges.
Development retains automatic metadata initialization for an empty local database.

Migration `0002_workspace_list_indexes` adds workspace/created-time/ID indexes for
agents, contacts, calls, campaigns, staff tasks, and audit history. PostgreSQL builds
these concurrently; allow migrations to finish before starting the new runtime.
Large deployments should apply migrations with one designated migration process.
These indexes improve the normal newest-first workspace list path; deep offset
pagination and substring searches may still need cursor or search indexes after
measurement.

Every HTTP response includes a locally generated `X-Request-ID`. Server failures log
that ID and duration without request paths, query strings, bodies or exception text.
Frontend diagnostics accept only a fixed event kind, HTTP status and a 32-character
request ID, require a session and same-origin checks, and have separate rate limits.
Provider failures in the voice paths omit response bodies and exception values;
utterances and TTS clauses are no longer logged. HTTP client INFO logs and Uvicorn
access logs are disabled to avoid query-string disclosure. Review reverse-proxy
logging policy separately before handling patient data.

Frontend release checks: `npm --prefix dashboard run lint`,
`npm --prefix dashboard run format:check`, and `npm --prefix dashboard run build`.
The build checks TypeScript and an initial-asset gzip budget. Email/password remains
in use; hospital SSO/MFA integration is intentionally deferred by the current product choice.
