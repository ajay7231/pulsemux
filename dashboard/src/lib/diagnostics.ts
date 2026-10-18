/** Fixed-schema, same-origin reporting. Never forward Error.message, stacks, URLs, or data. */
type Diagnostic = {
  kind:
    | "render_failure"
    | "unhandled_error"
    | "unhandled_rejection"
    | "api_failure";
  status?: number;
  request_id?: string;
};
let remaining = 10;
let windowStart = Date.now();
export function reportDiagnostic(event: Diagnostic) {
  if (Date.now() - windowStart > 60000) {
    remaining = 10;
    windowStart = Date.now();
  }
  if (remaining-- <= 0 || !navigator.onLine) return;
  const body: Diagnostic = { kind: event.kind, status: event.status || 0 };
  if (event.request_id && /^[a-f0-9]{32}$/.test(event.request_id))
    body.request_id = event.request_id;
  // Raw fetch deliberately avoids the API wrapper, preventing recursive failure reports.
  void fetch("/api/diagnostics", {
    method: "POST",
    credentials: "same-origin",
    cache: "no-store",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal: AbortSignal.timeout(5000),
  }).catch(() => {});
}
export function installDiagnostics() {
  window.addEventListener("error", () =>
    reportDiagnostic({ kind: "unhandled_error" }),
  );
  window.addEventListener("unhandledrejection", () =>
    reportDiagnostic({ kind: "unhandled_rejection" }),
  );
  window.addEventListener("application-error", () =>
    reportDiagnostic({ kind: "render_failure" }),
  );
}
