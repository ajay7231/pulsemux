import { Field, TimezoneSelect } from "../../components/ui";

import type { DialogFieldProps } from "./dialogTypes";
export function ContactFields({
  draft,
  input,
  setDraft,
  timezones,
  session,
}: Pick<
  DialogFieldProps,
  "draft" | "input" | "setDraft" | "timezones" | "session"
>) {
  return (
    <>
      <div className="form-grid">
        <Field label="Name">{input("name")}</Field>
        <Field label="Phone number" hint="Include + and country code.">
          {input("phone", "tel")}
        </Field>
      </div>
      <Field label="Timezone">
        <TimezoneSelect
          zones={timezones}
          value={draft.timezone || session.workspace.timezone}
          onChange={(e) => setDraft({ ...draft, timezone: e.target.value })}
        />
      </Field>
      <Field
        label="Agent variables (JSON)"
        hint='Example: {"appointment_date":"20 October","appointment_time":"10:00 AM"}'
      >
        <textarea
          rows={4}
          value={draft.variables || "{}"}
          onChange={(e) => setDraft({ ...draft, variables: e.target.value })}
        />
      </Field>
      <label className="checkbox-line">
        <input
          type="checkbox"
          checked={!!draft.consent}
          onChange={(e) => setDraft({ ...draft, consent: e.target.checked })}
        />
        Permission to receive automated calls has been recorded
      </label>
      <label className="checkbox-line">
        <input
          type="checkbox"
          checked={!!draft.opted_out}
          onChange={(e) => setDraft({ ...draft, opted_out: e.target.checked })}
        />
        Contact has opted out of automated calls
      </label>
    </>
  );
}
