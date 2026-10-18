import { ArrowRight, Plus } from "lucide-react";
import { Badge, Button, Field, TimezoneSelect } from "../../components/ui";
import { api } from "../../lib/api";
import type { WorkspacePageProps } from "./types";
type Props = Pick<
  WorkspacePageProps,
  | "session"
  | "busy"
  | "isAdmin"
  | "startModal"
  | "run"
  | "setNotice"
  | "setDocuments"
  | "setModal"
  | "formSubmit"
  | "setSession"
  | "timezones"
  | "data"
>;
export function SettingsPage({
  session,
  busy,
  isAdmin,
  startModal,
  run,
  setNotice,
  setDocuments,
  setModal,
  formSubmit,
  setSession,
  timezones,
  data,
}: Props) {
  return (
    <div className="settings-grid">
      <section className="card padded">
        <h2>Workspace</h2>
        <p className="muted">Hospital identity and conversation retention.</p>
        <form
          onSubmit={formSubmit(async () => {
            const form =
              document.querySelector<HTMLFormElement>("#workspace-form")!;
            const fields = new FormData(form);
            const workspace = await api("/workspace", "PUT", {
              name: fields.get("name"),
              timezone: fields.get("timezone"),
              retention_days: Number(fields.get("retention_days")),
            });
            setSession({ ...session, workspace });
            setNotice("Workspace saved");
          })}
          id="workspace-form"
        >
          <Field label="Name">
            <input name="name" defaultValue={session.workspace.name} required />
          </Field>
          <Field label="Timezone">
            <TimezoneSelect
              zones={timezones}
              name="timezone"
              defaultValue={session.workspace.timezone}
            />
          </Field>
          <Field label="Call retention (days)">
            <input
              type="number"
              min="1"
              max="3650"
              name="retention_days"
              defaultValue={session.workspace.retention_days}
            />
          </Field>
          <Button type="submit" disabled={busy || !isAdmin}>
            Save settings
          </Button>
        </form>
      </section>
      <section className="card padded">
        <div className="section-heading">
          <h2>Team access</h2>
          {isAdmin && (
            <Button onClick={() => startModal("user", { role: "operator" })}>
              <Plus size={15} />
              Add user
            </Button>
          )}
        </div>
        {data.map((u) => (
          <div className="user-row" key={u.id}>
            <span className="profile-avatar">{u.name[0]}</span>
            <div>
              <strong>{u.name}</strong>
              <small>{u.email}</small>
            </div>
            <Badge value={u.role} />
          </div>
        ))}
        <p className="muted">
          Administrators manage credentials and publish agents. Operators manage
          calls and drafts. Viewers have read-only access.
        </p>
        {isAdmin && (
          <Button
            onClick={() =>
              void run(async () => {
                setDocuments(await api("/audit"));
                setModal("audit");
              })
            }
          >
            View audit history
            <ArrowRight size={15} />
          </Button>
        )}
      </section>
    </div>
  );
}
