import { ShieldCheck } from "lucide-react";
import { Field } from "../../components/ui";

import type { DialogFieldProps } from "./dialogTypes";
export function ConnectionFields({
  draft,
  input,
  setDraft,
}: Pick<DialogFieldProps, "draft" | "input" | "setDraft">) {
  return (
    <>
      <Field label="Connection name">{input("name")}</Field>
      <Field label="Provider">
        <select
          disabled={!!draft.id}
          value={draft.provider}
          onChange={(e) =>
            setDraft({
              name: draft.name,
              provider: e.target.value,
              _agentField: draft._agentField,
              _providers: draft._providers,
            })
          }
        >
          {(draft._providers || ["deepgram", "groq", "openai", "twilio"]).map(
            (p: string) => (
              <option key={p} value={p}>
                {p === "openai" ? "OpenAI" : p[0].toUpperCase() + p.slice(1)}
              </option>
            ),
          )}
        </select>
      </Field>
      {draft.provider === "twilio" ? (
        <>
          <Field label="Account SID">{input("account_sid")}</Field>
          <Field
            label="Auth Token"
            hint="Required for signed webhook verification."
          >
            {input("auth_token", "password")}
          </Field>
          <Field label="API key SID (optional)">
            {input("api_key_sid", "text", false)}
          </Field>
          <Field label="API key secret (optional)">
            {input("api_key_secret", "password", false)}
          </Field>
        </>
      ) : (
        <Field label="API key">{input("api_key", "password")}</Field>
      )}
      <div className="info-panel">
        <ShieldCheck size={20} />
        <p>
          Encrypted before storage. Saved credentials cannot be revealed in the
          dashboard. Rotating a key replaces it for future requests.
        </p>
      </div>
    </>
  );
}
