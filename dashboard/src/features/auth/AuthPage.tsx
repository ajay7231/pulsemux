import { Activity, ArrowRight, ShieldCheck } from "lucide-react";
import React, { type FormEvent } from "react";
import { Link } from "react-router-dom";
import { Button, Field, TimezoneSelect } from "../../components/ui";
import { api } from "../../lib/api";
import type { Row } from "../../lib/types";

type AuthPageProps = {
  loading: boolean;
  setup: boolean;
  error: string;
  formSubmit: (fn: () => Promise<void>) => (event: FormEvent) => void;
  draft: Row;
  setSession: (value: unknown) => void;
  setDraft: React.Dispatch<React.SetStateAction<Row>>;
  setSetup: React.Dispatch<React.SetStateAction<boolean>>;
  setupTokenRequired: boolean;
  input: (key: string, type?: string, required?: boolean) => React.JSX.Element;
  timezones: string[];
  busy: boolean;
  setupAvailable: boolean;
};
export function AuthPage({
  loading,
  setup,
  error,
  formSubmit,
  draft,
  setSession,
  setDraft,
  setSetup,
  setupTokenRequired,
  input,
  timezones,
  busy,
  setupAvailable,
}: AuthPageProps) {
  return (
    <div className="auth-page">
      <div className="auth-brand">
        <div className="brand-mark">
          <Activity />
        </div>
        PulseMux<span>CLINICAL VOICE OPERATIONS</span>
      </div>
      <section className="auth-card">
        <h1>
          {loading
            ? "Connecting…"
            : setup
              ? "Create your workspace"
              : "Welcome back."}
        </h1>
        <p>
          {setup
            ? "Set up your hospital’s voice operations."
            : "Sign in to your clinical voice workspace."}
        </p>
        {error && (
          <div className="alert error" role="alert">
            {error}
          </div>
        )}
        {!loading && (
          <form
            onSubmit={formSubmit(async () => {
              const body = setup
                ? {
                    workspace: draft.workspace,
                    name: draft.name,
                    email: draft.email,
                    password: draft.password,
                    timezone: draft.timezone || "Asia/Kolkata",
                    setup_token: draft.setup_token || null,
                  }
                : { email: draft.email, password: draft.password };
              setSession(await api(setup ? "/setup" : "/login", "POST", body));
              setDraft({});
              setSetup(false);
            })}
          >
            {setup && (
              <>
                {setupTokenRequired && (
                  <Field
                    label="Installation setup token"
                    hint="Use the one-time setup token from your server configuration."
                  >
                    {input("setup_token", "password")}
                  </Field>
                )}
                <Field label="Hospital / workspace name">
                  {input("workspace")}
                </Field>
                <Field label="Your name">{input("name")}</Field>
                <Field
                  label="Timezone"
                  hint="Choose the timezone used by your hospital."
                >
                  <TimezoneSelect
                    zones={timezones}
                    value={draft.timezone || "Asia/Kolkata"}
                    onChange={(e) =>
                      setDraft({ ...draft, timezone: e.target.value })
                    }
                  />
                </Field>
              </>
            )}
            <Field label="Work email">{input("email", "email")}</Field>
            <Field
              label="Password"
              hint={setup ? "At least 12 characters." : ""}
            >
              <input
                type="password"
                autoComplete={setup ? "new-password" : "current-password"}
                required
                minLength={setup ? 12 : 1}
                value={draft.password || ""}
                onChange={(e) =>
                  setDraft({ ...draft, password: e.target.value })
                }
              />
            </Field>
            <Button type="submit" disabled={busy} kind="primary full">
              {busy ? "Please wait…" : setup ? "Create workspace" : "Sign in"}
              <ArrowRight size={17} />
            </Button>
          </form>
        )}
        {!loading && (
          <p className="auth-switch">
            {setup ? (
              <>
                Already have a workspace?{" "}
                <Link to="/dashboard/login">Sign in</Link>
              </>
            ) : (
              <>
                Use your hospital account to sign in.
                {setupAvailable && (
                  <>
                    <br />
                    <Link to="/dashboard/setup">Create a workspace</Link>
                  </>
                )}
              </>
            )}
          </p>
        )}
        <div className="auth-foot">
          <ShieldCheck size={15} />
          Self-hosted · Credentials encrypted at rest
        </div>
      </section>
    </div>
  );
}
