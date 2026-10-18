# PulseMux dashboard

React and TypeScript frontend for the self-hosted platform.

- `src/main.tsx`: mounts React and loads the dashboard styles.
- `src/App.tsx`: coordinates sessions, workspace data, navigation, and dialogs.
- `src/components/ui.tsx`: shared buttons, fields, badges, empty states, timezone
  selectors, and accessible modal behavior.
- `src/lib/`: API requests, shared types, configuration defaults, date formatting,
  and saved-agent fingerprints.
- `src/features/auth/`: workspace setup and sign-in presentation.
- `src/features/agents/`: agent editing, provider model discovery, and native call
  testing. Agent-specific styles and tests live alongside those components.
- `src/features/workspace/`: individual workspace pages and their typed contracts.
  `WorkspacePage` coordinates page headings and routing; `WorkspaceDialog` owns
  the workspace's create/edit/import dialogs.
- `src/features/calls/`: call tables and conversation details.

Page components receive state and actions explicitly through typed props. They
reuse shared controls and the API client. Server credentials remain managed by
the backend. The agent test component uses the shared browser call controller
in `worker-py/web/call.js` and releases its resources on unmount.

Run `npm test` for component and call-lifecycle tests, `npm run typecheck` for
TypeScript checks, and `npm run build` to publish frontend assets to the local
backend's `worker-py/web/dashboard` directory. This build does not deploy a site.
