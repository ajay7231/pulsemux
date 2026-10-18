import { QueryClientProvider } from "@tanstack/react-query";
import React from "react";
import { createRoot } from "react-dom/client";
import { RouterProvider } from "react-router-dom";
import { SessionProvider } from "./app/SessionProvider";
import { queryClient } from "./app/queryClient";
import { router } from "./app/router";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { installDiagnostics } from "./lib/diagnostics";
import "./styles.css";
installDiagnostics();
const rootElement = document.getElementById("root");
if (rootElement)
  createRoot(rootElement).render(
    <React.StrictMode>
      <ErrorBoundary>
        <QueryClientProvider client={queryClient}>
          <SessionProvider>
            <RouterProvider router={router} />
          </SessionProvider>
        </QueryClientProvider>
      </ErrorBoundary>
    </React.StrictMode>,
  );
