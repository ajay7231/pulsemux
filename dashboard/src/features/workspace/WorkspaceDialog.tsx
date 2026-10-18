import { ArrowRight, CalendarClock, Check } from "lucide-react";
import React, { type FormEvent } from "react";
import { Button, Field, Modal } from "../../components/ui";
import type { ConfigUpdate, Session } from "../../contracts/schemas";
import { api } from "../../lib/api";
import { Page, Row } from "../../lib/types";
import { connectionService, operationService } from "../../services/platform";
import { AuditLog } from "./AuditLog";
import { ConnectionFields } from "./ConnectionFields";
import { ContactFields } from "./ContactFields";
import { DocumentsDialog } from "./DocumentsDialog";
import { ImportContactsDialog } from "./ImportContactsDialog";
import { OutreachFields } from "./OutreachFields";

type WorkspaceDialogProps = {
  initial: Row;
  selected: Row | null;
  modal: string;
  setModal: React.Dispatch<React.SetStateAction<string>>;
  error: string;
  templates: Row[];
  newAgent: (template?: Row) => void;
  formSubmit: (fn: () => Promise<void>) => (event: FormEvent) => void;
  cf: ConfigUpdate;
  setConnections: React.Dispatch<React.SetStateAction<Row[]>>;
  saveDone: (message: string) => void;
  setDocuments: React.Dispatch<React.SetStateAction<Row[]>>;
  setNotice: React.Dispatch<React.SetStateAction<string>>;
  session: Session;
  navigate: (next: Page) => void;
  connections: Row[];
  agents: Row[];
  timezones: string[];
  numbers: Row[];
  busy: boolean;
  run: (fn: () => Promise<void>) => Promise<void>;
  canEdit: boolean;
  documents: Row[];
  isAdmin: boolean;
  refresh: () => void;
};
export function WorkspaceDialog({
  initial,
  selected,
  modal,
  setModal,
  error,
  templates,
  newAgent,
  formSubmit,
  cf,
  setConnections,
  saveDone,
  setDocuments,
  setNotice,
  session,
  navigate,
  connections,
  agents,
  timezones,
  numbers,
  busy,
  run,
  canEdit,
  documents,
  isAdmin,
  refresh,
}: WorkspaceDialogProps) {
  const [draft, setDraft] = React.useState<Row>(() => structuredClone(initial));
  const input = (key: string, type = "text", required = true) => (
    <input
      type={type}
      required={required}
      value={draft[key] ?? ""}
      onChange={(e) => setDraft({ ...draft, [key]: e.target.value })}
    />
  );
  const select = (
    key: string,
    items: Row[],
    label = "name",
    empty = "Choose…",
  ) => (
    <select
      required
      value={draft[key] ?? ""}
      onChange={(e) => setDraft({ ...draft, [key]: e.target.value })}
    >
      <option value="">{empty}</option>
      {items.map((row) => (
        <option key={row.id} value={row.id}>
          {row[label]}
        </option>
      ))}
    </select>
  );

  return (
    <Modal
      title={
        (
          {
            templates: "Choose a starting point",
            connection: draft.id ? "Rotate credentials" : "Add a connection",
            collection: "New knowledge collection",
            documents: selected?.name,
            document: "Add reference document",
            number: "Assign a phone number",
            "number-help": "Connect your Twilio number",
            contact: draft.id ? "Edit contact" : "Add contact",
            campaign: "Create a campaign",
            outbound: "Place an outbound call",
            user: "Add a team member",
            audit: "Workspace audit history",
            import: "Import contacts",
            help: "Your clinical voice workspace",
          } as Row
        )[modal] || modal
      }
      subtitle={
        modal === "templates"
          ? "Start with a workflow. Customize every conversation."
          : undefined
      }
      onClose={() => setModal("")}
      wide={["templates", "documents", "audit"].includes(modal)}
    >
      {error && (
        <div className="alert error modal-error" role="alert">
          {error}
        </div>
      )}
      {modal === "templates" && (
        <div className="template-grid">
          {templates.map((t) => (
            <button
              key={t.id}
              className="template-card"
              onClick={() => newAgent(t)}
            >
              <div className="agent-symbol">
                <CalendarClock size={20} />
              </div>
              <h3>{t.name}</h3>
              <p>{t.description}</p>
              <span>
                Use template
                <ArrowRight size={15} />
              </span>
            </button>
          ))}
        </div>
      )}
      {[
        "connection",
        "collection",
        "document",
        "number",
        "contact",
        "campaign",
        "outbound",
        "user",
      ].includes(modal) && (
        <form
          className="modal-form"
          onSubmit={formSubmit(async () => {
            if (modal === "connection") {
              const credentials: Record<string, string> =
                draft.provider === "twilio"
                  ? {
                      account_sid: draft.account_sid,
                      auth_token: draft.auth_token,
                      ...(draft.api_key_sid
                        ? {
                            api_key_sid: draft.api_key_sid,
                            api_key_secret: draft.api_key_secret,
                          }
                        : {}),
                    }
                  : { api_key: draft.api_key };
              const savedConnection = await connectionService.save(
                { name: draft.name, provider: draft.provider, credentials },
                draft.id,
              );
              if (draft._agentField) {
                cf(draft._agentField, savedConnection.id);
                if (draft._agentField === "llm_connection_id")
                  cf("llm_model", "");
              }
              setConnections((prev) => [
                ...prev.filter((c) => c.id !== savedConnection.id),
                savedConnection,
              ]);
              setDraft({});
              saveDone("Connection saved securely");
            }
            if (modal === "collection") {
              await api("/collections", "POST", {
                name: draft.name,
                description: draft.description || "",
                embedding_connection_id: draft.embedding_connection_id || null,
              });
              saveDone("Collection created");
            }
            if (modal === "document") {
              await api(`/collections/${selected!.id}/documents`, "POST", {
                title: draft.title,
                content: draft.content,
              });
              setDocuments(await operationService.documents(selected!.id));
              setModal("documents");
              setNotice(
                "Document saved as draft. An administrator must approve it.",
              );
            }
            if (modal === "number") {
              await api("/numbers", "POST", {
                number: draft.number,
                label: draft.label || "",
                agent_id: draft.agent_id,
                connection_id: draft.connection_id,
              });
              saveDone(
                "Number assigned. Configure its Twilio inbound webhook to finish setup.",
              );
            }
            if (modal === "contact") {
              let variables;
              try {
                variables = JSON.parse(draft.variables || "{}");
              } catch {
                throw new Error("Variables must be valid JSON");
              }
              await api(
                "/contacts" + (draft.id ? "/" + draft.id : ""),
                draft.id ? "PUT" : "POST",
                {
                  name: draft.name,
                  phone: draft.phone,
                  consent: !!draft.consent,
                  opted_out: !!draft.opted_out,
                  timezone: draft.timezone || session.workspace.timezone,
                  variables,
                },
              );
              saveDone("Contact saved");
            }
            if (modal === "campaign") {
              if (!draft.contact_ids?.length)
                throw new Error("Select at least one eligible contact.");
              await api("/campaigns", "POST", {
                ...draft,
                starts_at: new Date(draft.starts_at).getTime() / 1000,
              });
              saveDone("Campaign created as draft. Review it before starting.");
            }
            if (modal === "outbound") {
              if (!draft.contact_id)
                throw new Error("Select an eligible contact.");
              const result = await operationService.outbound({
                agent_id: draft.agent_id,
                phone_number_id: draft.phone_number_id,
                contact_id: draft.contact_id,
              });
              saveDone(result.error || "Call requested");
              navigate("calls");
            }
            if (modal === "user") {
              await api("/users", "POST", draft);
              saveDone("Team member added");
            }
          })}
        >
          {modal === "connection" && (
            <ConnectionFields draft={draft} input={input} setDraft={setDraft} />
          )}
          {modal === "collection" && (
            <>
              <Field label="Collection name">{input("name")}</Field>
              <Field label="Description">
                {input("description", "text", false)}
              </Field>
              <Field
                label="Semantic search (optional)"
                hint="OpenAI embeddings are billed to your account. Without a connection, approved documents use keyword retrieval."
              >
                <select
                  value={draft.embedding_connection_id || ""}
                  onChange={(e) =>
                    setDraft({
                      ...draft,
                      embedding_connection_id: e.target.value,
                    })
                  }
                >
                  <option value="">Keyword search only</option>
                  {connections
                    .filter((c) => c.active && c.provider === "openai")
                    .map((c) => (
                      <option key={c.id} value={c.id}>
                        {c.name}
                      </option>
                    ))}
                </select>
              </Field>
            </>
          )}
          {modal === "document" && (
            <>
              <Field label="Document title">{input("title")}</Field>
              <Field label="Reference text">
                <textarea
                  required
                  rows={12}
                  value={draft.content || ""}
                  onChange={(e) =>
                    setDraft({ ...draft, content: e.target.value })
                  }
                />
              </Field>
            </>
          )}
          {modal === "number" && (
            <>
              <Field
                label="Twilio phone number"
                hint="Use a number owned by the selected Twilio account, including country code."
              >
                {input("number", "tel")}
              </Field>
              <Field label="Label">{input("label", "text", false)}</Field>
              <Field label="Twilio connection">
                {select(
                  "connection_id",
                  connections.filter(
                    (c) => c.active && c.provider === "twilio",
                  ),
                )}
              </Field>
              <Field label="Inbound agent">{select("agent_id", agents)}</Field>
            </>
          )}
          {modal === "contact" && (
            <ContactFields
              draft={draft}
              input={input}
              setDraft={setDraft}
              timezones={timezones}
              session={session}
            />
          )}
          {(modal === "campaign" || modal === "outbound") && (
            <OutreachFields
              modal={modal}
              input={input}
              select={select}
              agents={agents}
              numbers={numbers}
              draft={draft}
              setDraft={setDraft}
            />
          )}
          {modal === "user" && (
            <>
              <Field label="Full name">{input("name")}</Field>
              <Field label="Email">{input("email", "email")}</Field>
              <Field
                label="Initial password"
                hint="At least 12 characters. Share through a secure channel."
              >
                {input("password", "password")}
              </Field>
              <Field label="Role">
                <select
                  value={draft.role}
                  onChange={(e) => setDraft({ ...draft, role: e.target.value })}
                >
                  {["admin", "operator", "viewer"].map((r) => (
                    <option key={r}>{r}</option>
                  ))}
                </select>
              </Field>
            </>
          )}
          <div className="modal-footer">
            <Button onClick={() => setModal("")}>Cancel</Button>
            <Button type="submit" kind="primary" disabled={busy}>
              {busy
                ? "Saving…"
                : modal === "outbound"
                  ? "Place call"
                  : modal === "campaign"
                    ? "Save campaign draft"
                    : "Save"}
              <Check size={16} />
            </Button>
          </div>
        </form>
      )}
      {modal === "import" && (
        <ImportContactsDialog
          draft={draft}
          setDraft={setDraft}
          run={run}
          saveDone={saveDone}
          setModal={setModal}
          busy={busy}
        />
      )}
      {modal === "documents" && (
        <DocumentsDialog
          canEdit={canEdit}
          setDraft={setDraft}
          setModal={setModal}
          run={run}
          selected={selected}
          setDocuments={setDocuments}
          setNotice={setNotice}
          documents={documents}
          isAdmin={isAdmin}
          busy={busy}
          refresh={refresh}
        />
      )}
      {modal === "number-help" && (
        <div className="modal-content">
          <p>
            In the Twilio Console, open <strong>{selected?.number}</strong>.
            Under Voice configuration, set “A call comes in” to Webhook (HTTP
            POST):
          </p>
          <pre>
            {location.origin}/api/twilio/{selected?.connection_id}/inbound
          </pre>
          <p className="muted">
            Use your deployment’s public HTTPS origin. Set the same origin as
            PUBLIC_BASE_URL on the server. Incoming requests and media
            connections are signature-validated.
          </p>
        </div>
      )}
      {modal === "audit" && <AuditLog />}
      {modal === "help" && (
        <div className="modal-content">
          <h3>From configuration to conversation</h3>
          <ol>
            <li>Add your speech, language model, and Twilio connections.</li>
            <li>Create an agent from a workflow template.</li>
            <li>Attach approved knowledge, then save and test the draft.</li>
            <li>Publish the tested agent and assign a number.</li>
            <li>Place a call or create an outreach campaign.</li>
          </ol>
          <p>
            Real telephone calls need a public HTTPS origin, an owned Twilio
            number, and a running campaign worker. Appointment changes currently
            create staff requests.
          </p>
          <p className="muted">
            Deployments handling patient information need reviewed operating
            procedures and provider agreements. No call audio is recorded by
            this platform.
          </p>
        </div>
      )}
    </Modal>
  );
}
