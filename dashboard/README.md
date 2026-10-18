# PulseMux dashboard

React and TypeScript frontend for the self-hosted platform.

- `src/main.tsx`: mounts providers, error recovery, and the router.
- `src/app/router.tsx`: nested public/private routes, dynamic agent IDs and fallbacks.
- `src/app/SessionProvider.tsx`: session restoration, expiry, cross-tab changes and logout.
- `src/app/queryClient.ts`: workspace query caching and bounded read retries.
- `src/app/useWorkspaceQueries.ts`: paginated lists and on-demand selection data.
- `src/App.tsx`: authenticated workspace shell, local editor state and dialogs.
- `src/services/platform.ts`: typed endpoint operations and response validation.
- `src/contracts/`: generated OpenAPI DTOs and runtime Zod schemas.
- `src/components/ui.tsx`: shared buttons, fields, badges, empty states, timezone
  selectors, and accessible modal behavior.
- `src/lib/`: API requests, shared types, configuration defaults, date formatting,
  and saved-agent fingerprints.
- `src/features/auth/`: workspace setup and sign-in presentation.
- `src/features/agents/`: agent editing, provider model discovery, and native call
  testing. Agent-specific styles and tests live alongside those components.
- `src/features/workspace/`: individual workspace pages and their typed contracts.
  `WorkspacePage` coordinates page headings and list presentation; `WorkspaceDialog` owns
  the workspace's create/edit dialogs and owns their local draft state. Connection, contact, outreach, import, and document workflows have separate components.
- `src/features/calls/`: call tables and conversation details.

Page components receive state and actions explicitly through typed props. They
reuse shared controls and the API client. Server credentials remain managed by
the backend. The agent test component uses the shared browser call controller
in `worker-py/web/call.js` and releases its resources on unmount.

Run `npm run lint`, `npm run format:check`, and `npm run typecheck` for source
quality checks. `npm run build` writes frontend assets to the local
backend's `worker-py/web/dashboard` directory. This build does not deploy a site.

Regenerate DTOs after backend contract changes with `npm run contracts`. This
exports the FastAPI schema without connecting to the database and regenerates
`src/contracts/generated.ts`. Runtime schemas validate the core response paths;
the HTTP client returns `unknown` by default and preserves structured failures.

The browser uses history URLs under `/dashboard/`; backend serving must retain
the corresponding HTML fallback while serving `/dashboard/assets` separately.
Feature modules are loaded on demand. Secrets and patient records are never
persisted to browser storage; the session synchronization marker contains only
an event kind and random nonce. Agent configuration fields and defaults use the validated `AgentConfig` contract and typed updates. Some legacy heterogeneous resource and form dictionaries still use `Row`; narrow these at feature boundaries when extending forms.


P2/P3 implementation notes:

- `AgentEditor` owns page actions; `AgentConfiguration` owns workflow and policy sections; `VoiceConfiguration` owns speech/model settings.
  `WorkspaceDialog` keeps draft values local; document and CSV workflows are separate components.
- Native top-layer dialogs provide modal background inertness, focus containment,
  Escape dismissal, and focus restoration. Route navigation restores heading focus;
  a skip link and reduced-motion styles support keyboard and motion preferences.
- `lib/diagnostics.ts` sends only fixed event kinds, HTTP status and generated request IDs
  to the authenticated same-origin diagnostics endpoint. Messages, stacks, URLs,
  credentials, and conversation text are excluded. Reports are bounded in the browser
  and rate limited on the server. Server error references can be matched to logs.
- Campaign/outbound contact selection searches and pages remotely in batches of 25;
  selected IDs persist across pages. Model catalogs are cached by workspace, connection
  and credential revision. Unrelated dialogs no longer preload all selection resources.
- `npm run build` enforces a 220 KiB gzip budget for the entry bundle and its static
  JS/CSS dependencies via Vite's manifest. Lazy feature chunks are reported by Vite
  separately. This is a bundle-size gate, not a claim about observed patient-call latency.
- ESLint enforces unused-code and shared-layer import boundaries. Formatting and fixes
  exclude generated contracts and existing test/spec files. The simulator's UI and
  stylesheet remain normal application source.

Email/password login remains the selected authentication approach. SSO/MFA is deferred
until requested with an identity policy. Virtualization is deferred for lists already
bounded to 25 visible records; revisit it if measured document/selection workloads justify it.
