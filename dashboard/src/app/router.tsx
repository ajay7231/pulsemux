import { lazy, Suspense } from "react";
import {
  createBrowserRouter,
  isRouteErrorResponse,
  Navigate,
  Outlet,
  useLocation,
  useMatches,
  useRouteError,
} from "react-router-dom";
import { ErrorBoundary } from "../components/ErrorBoundary";
import type { Page } from "../lib/types";
import { NavigationRecovery } from "./NavigationRecovery";
import { useSession } from "./SessionProvider";
const App = lazy(() =>
  import("../App").then((module) => ({ default: module.App })),
);
const Auth = lazy(() =>
  import("../features/auth/AuthScreen").then((module) => ({
    default: module.AuthScreen,
  })),
);
export type DashboardRoute = {
  page: Page;
  mode?: "new" | "edit" | "simulate";
  notFound?: boolean;
  role?: "operator" | "admin";
};
export function useDashboardRoute() {
  const matches = useMatches();
  const match = matches.at(-1)!;
  return { ...(match.handle as DashboardRoute), agentId: match.params.agentId };
}
function Loading() {
  return (
    <div className="loading" role="status">
      Connecting to your workspace…
    </div>
  );
}
function Gate({ privateRoute = false }: { privateRoute?: boolean }) {
  const auth = useSession();
  const location = useLocation();
  if (auth.status === "loading") return <Loading />;
  if (auth.status === "unavailable")
    return (
      <section className="auth-page">
        <div className="card padded" role="alert">
          <h1>Workspace unavailable</h1>
          <p>{auth.error}</p>
          <button className="button primary" onClick={auth.reload}>
            Try again
          </button>
        </div>
      </section>
    );
  if (privateRoute && auth.status !== "authenticated")
    return (
      <Navigate
        to={
          location.hash === "#login"
            ? "/dashboard/login"
            : auth.setupRequired
              ? "/dashboard/setup"
              : "/dashboard/login"
        }
        state={{ returnTo: location.pathname + location.search }}
        replace
      />
    );
  return (
    <ErrorBoundary resetKey={location.pathname}>
      <Suspense fallback={<Loading />}>
        {!privateRoute && <NavigationRecovery />}
        <Outlet />
      </Suspense>
    </ErrorBoundary>
  );
}
export function NotFound() {
  return (
    <section className="card padded">
      <h1>Page not found</h1>
      <p>The page or record address is invalid.</p>
      <a className="button primary" href="/dashboard/overview">
        Go to overview
      </a>
    </section>
  );
}
function RouteFailure() {
  const error = useRouteError();
  if (isRouteErrorResponse(error) && error.status === 404) return <NotFound />;
  return (
    <section className="card padded" role="alert">
      <h1>This page couldn’t be loaded.</h1>
      <p>Reload the application or return to your workspace.</p>
      <button className="button primary" onClick={() => location.reload()}>
        Reload
      </button>
      <a className="button" href="/dashboard/overview">
        Go to overview
      </a>
    </section>
  );
}
function WorkspaceShell() {
  const { session } = useSession();
  return <App key={`${session!.user.id}:${session!.user.role}`} />;
}
export const router = createBrowserRouter([
  {
    path: "/dashboard",
    element: <Gate />,
    errorElement: <RouteFailure />,
    children: [
      { path: "login", element: <Auth /> },
      { path: "setup", element: <Auth /> },
      {
        element: <Gate privateRoute />,
        children: [
          {
            element: <WorkspaceShell />,
            children: [
              {
                index: true,
                element: <Navigate to="/dashboard/overview" replace />,
                handle: { page: "overview" },
              },
              ...(
                [
                  "overview",
                  "agents",
                  "knowledge",
                  "connections",
                  "numbers",
                  "contacts",
                  "campaigns",
                  "calls",
                  "tasks",
                  "settings",
                ] as Page[]
              ).map((page) => ({ path: page, handle: { page } })),
              {
                path: "agents/new",
                handle: { page: "agents", mode: "new", role: "operator" },
              },
              {
                path: "agents/:agentId",
                handle: { page: "agents", mode: "edit" },
              },
              {
                path: "agents/:agentId/simulate",
                handle: { page: "agents", mode: "simulate", role: "operator" },
              },
              {
                path: "*",
                element: <NotFound />,
                handle: { page: "overview", notFound: true },
              },
            ],
          },
        ],
      },
    ],
  },
  { path: "*", element: <NotFound /> },
]);
