import { QueryClient } from "@tanstack/react-query";
import { ApiError } from "../lib/api";
export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30000,
      gcTime: 300000,
      refetchOnWindowFocus: true,
      retry: (count, error) =>
        count < 2 &&
        error instanceof ApiError &&
        (error.status === 0 || error.status >= 500 || error.status === 429),
      retryDelay: (attempt, error) =>
        error instanceof ApiError && error.retryAfter
          ? Math.min(error.retryAfter * 1000, 30000)
          : Math.min(1000 * 2 ** attempt, 10000),
    },
    mutations: { retry: false },
  },
});

window.addEventListener("resource-mutated", (event) => {
  const resource = (event as CustomEvent<{ resource: string }>).detail.resource;
  const affected =
    resource === "documents" ? ["collections", "agents"] : [resource];
  void queryClient.invalidateQueries({
    predicate: (query) =>
      query.queryKey[0] === "workspace" &&
      (query.queryKey[2] === "overview" ||
        affected.includes(String(query.queryKey[3])) ||
        (affected.includes("agents") && query.queryKey[2] === "agent")),
  });
});
