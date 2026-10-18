import { useQuery } from "@tanstack/react-query";
import { useEffect, useState, type FormEvent } from "react";
import { Navigate, useLocation } from "react-router-dom";
import { useSession } from "../../app/SessionProvider";
import { api } from "../../lib/api";
import type { Row } from "../../lib/types";
import { AuthPage } from "./AuthPage";
export function AuthScreen() {
  const auth = useSession();
  const location = useLocation();
  const setup = location.pathname.endsWith("/setup") && auth.setupRequired;
  const [draft, setDraft] = useState<Row>({});
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const zones = useQuery({
    queryKey: ["timezones"],
    queryFn: ({ signal }) =>
      api<string[]>("/timezones", "GET", undefined, {
        signal,
        auth: "optional",
      }),
    staleTime: Infinity,
  });
  useEffect(() => {
    setDraft((previous) => ({ ...previous, password: "", setup_token: "" }));
    setError("");
  }, [setup]);
  const returnTo =
    typeof location.state?.returnTo === "string" &&
    location.state.returnTo.startsWith("/dashboard/") &&
    !location.state.returnTo.includes("//")
      ? location.state.returnTo
      : "/dashboard/overview";
  if (auth.status === "authenticated")
    return <Navigate to={returnTo} replace />;
  if (location.pathname.endsWith("/setup") && !auth.setupRequired)
    return <Navigate to="/dashboard/login" replace />;
  const formSubmit = (fn: () => Promise<void>) => (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError("");
    void fn()
      .catch((error) => setError(error.message))
      .finally(() => setBusy(false));
  };
  const input = (key: string, type = "text", required = true) => (
    <input
      type={type}
      required={required}
      value={draft[key] ?? ""}
      autoComplete={key === "email" ? "username" : undefined}
      onChange={(event) => setDraft({ ...draft, [key]: event.target.value })}
    />
  );
  return (
    <AuthPage
      loading={false}
      setup={setup}
      error={error || auth.error}
      formSubmit={formSubmit}
      draft={draft}
      setSession={auth.setSession}
      setDraft={setDraft}
      setSetup={() => {}}
      setupTokenRequired={auth.setupTokenRequired}
      input={input}
      timezones={zones.data || ["Asia/Kolkata", "UTC"]}
      busy={busy}
      setupAvailable={auth.setupRequired}
    />
  );
}
