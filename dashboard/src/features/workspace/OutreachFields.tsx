import { Phone } from "lucide-react";
import { Field } from "../../components/ui";
import { ContactPicker } from "./ContactPicker";

import type { DialogFieldProps } from "./dialogTypes";
export function OutreachFields({
  modal,
  input,
  select,
  agents,
  numbers,
  draft,
  setDraft,
}: Pick<
  DialogFieldProps,
  "modal" | "input" | "select" | "agents" | "numbers" | "draft" | "setDraft"
>) {
  return (
    <>
      {modal === "campaign" && (
        <Field label="Campaign name">{input("name")}</Field>
      )}
      <Field label="Published agent">
        {select(
          "agent_id",
          agents.filter((a) => a.status === "published"),
        )}
      </Field>
      <Field label="Outbound caller ID">
        {select(
          "phone_number_id",
          numbers.map((n) => ({ ...n, name: n.number })),
        )}
      </Field>
      {modal === "outbound" ? (
        <div className="field">
          <span>Contact</span>
          <ContactPicker
            value={draft.contact_id ? [draft.contact_id] : []}
            onChange={(ids) => setDraft({ ...draft, contact_id: ids[0] || "" })}
          />
        </div>
      ) : (
        <>
          <Field label="Start at (your browser timezone)">
            {input("starts_at", "datetime-local")}
          </Field>
          <div className="form-grid">
            {[
              ["window_start", "Calling window starts (hour)"],
              ["window_end", "Calling window ends (hour)"],
              ["concurrency", "Concurrent calls"],
              ["max_attempts", "Maximum attempts"],
              ["retry_minutes", "Retry delay (minutes)"],
            ].map(([key, label]) => (
              <Field key={key} label={label}>
                <input
                  type="number"
                  required
                  value={draft[key]}
                  onChange={(e) =>
                    setDraft({
                      ...draft,
                      [key]: Number(e.target.value),
                    })
                  }
                />
              </Field>
            ))}
          </div>
          <div className="field">
            <span>Audience</span>
            <ContactPicker
              multiple
              value={draft.contact_ids || []}
              onChange={(ids) => setDraft({ ...draft, contact_ids: ids })}
            />
          </div>
          <p className="muted">
            Calling windows use each contact’s timezone. Consent and opt-out are
            rechecked before every attempt.
          </p>
        </>
      )}
      <div className="info-panel">
        <Phone size={20} />
        <p>
          {modal === "outbound"
            ? "Submitting this form places a real call through the selected telephone provider account."
            : "Campaigns are saved as drafts. Start them from the campaign list when ready."}
        </p>
      </div>
    </>
  );
}
