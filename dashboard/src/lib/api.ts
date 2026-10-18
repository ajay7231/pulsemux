import type { Row } from "./types";
export async function api<T = any>(
  path: string,
  method = "GET",
  body?: unknown,
  options: { signal?: AbortSignal } = {},
): Promise<T> {
  const response = await fetch("/api" + path, {
    method,
    signal: options.signal,
    credentials: "same-origin",
    headers:
      body instanceof FormData
        ? {}
        : body !== undefined
          ? { "Content-Type": "application/json" }
          : {},
    body:
      body instanceof FormData
        ? body
        : body !== undefined
          ? JSON.stringify(body)
          : undefined,
  });
  const result = await response
    .json()
    .catch(() => ({ detail: "The server returned an invalid response" }));
  if (!response.ok) {
    const detail = result.detail;
    throw new Error(
      typeof detail === "string"
        ? detail
        : Array.isArray(detail)
          ? detail
              .map((e: Row) => `${e.loc?.slice(1).join(".")}: ${e.msg}`)
              .join("; ")
          : "Request failed",
    );
  }
  return result as T;
}
