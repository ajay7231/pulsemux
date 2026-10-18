import { reportDiagnostic } from "./diagnostics";
export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly code: string,
    readonly requestId?: string,
    readonly retryAfter?: number,
  ) {
    super(
      requestId && status >= 500 && /^[a-f0-9]{32}$/.test(requestId)
        ? `${message} (Reference: ${requestId})`
        : message,
    );
    this.name = "ApiError";
  }
}
export type ApiOptions = {
  signal?: AbortSignal;
  timeoutMs?: number;
  auth?: "required" | "optional";
};
function message(detail: unknown): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail))
    return detail
      .map((error) => {
        if (!error || typeof error !== "object") return "Invalid input";
        const item = error as { loc?: unknown[]; msg?: string };
        return `${item.loc?.slice(1).join(".") || "Input"}: ${item.msg || "Invalid value"}`;
      })
      .join("; ");
  return "The request could not be completed.";
}

// Low-level responses remain unknown until a domain service validates them.
// Request DTOs are generated from the backend's OpenAPI contract.
export async function api<T = unknown>(
  path: string,
  method = "GET",
  body?: unknown,
  options: ApiOptions = {},
): Promise<T> {
  const controller = new AbortController();
  const abort = () => controller.abort(options.signal?.reason);
  if (options.signal?.aborted) abort();
  else options.signal?.addEventListener("abort", abort, { once: true });
  const timeout = setTimeout(
    () =>
      controller.abort(new DOMException("Request timed out", "TimeoutError")),
    options.timeoutMs ?? 15000,
  );
  try {
    const response = await fetch("/api" + path, {
      method,
      signal: controller.signal,
      credentials: "same-origin",
      cache: "no-store",
      headers:
        body !== undefined && !(body instanceof FormData)
          ? { "Content-Type": "application/json" }
          : {},
      body:
        body instanceof FormData
          ? body
          : body !== undefined
            ? JSON.stringify(body)
            : undefined,
    });
    if (response.status === 401 && options.auth !== "optional")
      window.dispatchEvent(new Event("session-expired"));
    let result: unknown;
    try {
      result = response.status === 204 ? undefined : await response.json();
    } catch {
      throw new ApiError(
        "The server returned an invalid response.",
        response.status,
        "invalid_response",
        response.headers.get("x-request-id") || undefined,
      );
    }
    if (response.status >= 500)
      reportDiagnostic({
        kind: "api_failure",
        status: response.status,
        request_id: response.headers.get("x-request-id") || undefined,
      });
    if (!response.ok) {
      throw new ApiError(
        message((result as { detail?: unknown })?.detail),
        response.status,
        response.status === 401
          ? "unauthorized"
          : response.status === 403
            ? "forbidden"
            : "http_error",
        response.headers.get("x-request-id") || undefined,
        Number(response.headers.get("retry-after")) || undefined,
      );
    }
    if (!["GET", "HEAD", "OPTIONS"].includes(method)) {
      const resource = path.split("/")[1];
      window.dispatchEvent(
        new CustomEvent("resource-mutated", { detail: { resource } }),
      );
    }
    return result as T;
  } catch (error) {
    if (error instanceof ApiError || options.signal?.aborted) throw error;
    if (controller.signal.aborted)
      throw new ApiError(
        method === "GET"
          ? "The server took too long to respond. Please retry."
          : "The server did not confirm the result. Refresh the record before submitting again.",
        0,
        "timeout",
      );
    throw new ApiError(
      method === "GET"
        ? "Cannot reach the server. Check your connection and retry."
        : "The operation could not be confirmed. Check the record before submitting again.",
      0,
      "network",
    );
  } finally {
    clearTimeout(timeout);
    options.signal?.removeEventListener("abort", abort);
  }
}
