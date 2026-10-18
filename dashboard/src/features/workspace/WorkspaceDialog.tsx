import {
  Activity,
  ArrowRight,
  CalendarClock,
  Check,
  FileText,
  Phone,
  Plus,
  ShieldCheck,
  Upload,
} from "lucide-react";
import React, { type FormEvent } from "react";
import {
  Badge,
  Button,
  Empty,
  Field,
  Modal,
  TimezoneSelect,
} from "../../components/ui";
import { api } from "../../lib/api";
import { date } from "../../lib/format";
import { Page, Row } from "../../lib/types";

type WorkspaceDialogProps = {
  draft: Row;
  selected: Row | null;
  modal: string;
  setModal: React.Dispatch<React.SetStateAction<string>>;
  error: string;
  templates: Row[];
  newAgent: (template?: Row) => void;
  formSubmit: (fn: () => Promise<void>) => (event: FormEvent) => void;
  cf: (key: string, value: any) => void;
  setConnections: React.Dispatch<React.SetStateAction<Row[]>>;
  setDraft: React.Dispatch<React.SetStateAction<Row>>;
  saveDone: (message: string) => void;
  setDocuments: React.Dispatch<React.SetStateAction<Row[]>>;
  setNotice: React.Dispatch<React.SetStateAction<string>>;
  session: Row;
  navigate: (next: Page) => void;
  input: (key: string, type?: string, required?: boolean) => React.JSX.Element;
  connections: Row[];
  select: (
    key: string,
    items: Row[],
    label?: string,
    empty?: string,
  ) => React.JSX.Element;
  agents: Row[];
  timezones: string[];
  numbers: Row[];
  contacts: Row[];
  busy: boolean;
  run: (fn: () => Promise<void>) => Promise<void>;
  canEdit: boolean;
  documents: Row[];
  isAdmin: boolean;
  refresh: () => void;
};
export function WorkspaceDialog({
  draft,
  selected,
  modal,
  setModal,
  error,
  templates,
  newAgent,
  formSubmit,
  cf,
  setConnections,
  setDraft,
  saveDone,
  setDocuments,
  setNotice,
  session,
  navigate,
  input,
  connections,
  select,
  agents,
  timezones,
  numbers,
  contacts,
  busy,
  run,
  canEdit,
  documents,
  isAdmin,
  refresh,
}: WorkspaceDialogProps) {
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
              const credentials =
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
              const savedConnection = await api(
                "/connections" + (draft.id ? "/" + draft.id : ""),
                draft.id ? "PUT" : "POST",
                { name: draft.name, provider: draft.provider, credentials },
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
              setDocuments(await api(`/collections/${selected!.id}/documents`));
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
              await api("/campaigns", "POST", {
                ...draft,
                starts_at: new Date(draft.starts_at).getTime() / 1000,
              });
              saveDone("Campaign created as draft. Review it before starting.");
            }
            if (modal === "outbound") {
              const result = await api("/calls/outbound", "POST", draft);
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
                  {(
                    draft._providers || ["deepgram", "groq", "openai", "twilio"]
                  ).map((p: string) => (
                    <option key={p} value={p}>
                      {p === "openai"
                        ? "OpenAI"
                        : p[0].toUpperCase() + p.slice(1)}
                    </option>
                  ))}
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
                  Encrypted before storage. Saved credentials cannot be revealed
                  in the dashboard. Rotating a key replaces it for future
                  requests.
                </p>
              </div>
            </>
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
                  onChange={(e) =>
                    setDraft({ ...draft, timezone: e.target.value })
                  }
                />
              </Field>
              <Field
                label="Agent variables (JSON)"
                hint='Example: {"appointment_date":"20 October","appointment_time":"10:00 AM"}'
              >
                <textarea
                  rows={4}
                  value={draft.variables || "{}"}
                  onChange={(e) =>
                    setDraft({ ...draft, variables: e.target.value })
                  }
                />
              </Field>
              <label className="checkbox-line">
                <input
                  type="checkbox"
                  checked={!!draft.consent}
                  onChange={(e) =>
                    setDraft({ ...draft, consent: e.target.checked })
                  }
                />
                Permission to receive automated calls has been recorded
              </label>
              <label className="checkbox-line">
                <input
                  type="checkbox"
                  checked={!!draft.opted_out}
                  onChange={(e) =>
                    setDraft({ ...draft, opted_out: e.target.checked })
                  }
                />
                Contact has opted out of automated calls
              </label>
            </>
          )}
          {(modal === "campaign" || modal === "outbound") && (
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
                <Field label="Contact">
                  {select(
                    "contact_id",
                    contacts.filter((c) => c.consent && !c.opted_out),
                  )}
                </Field>
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
                  <Field label="Audience">
                    <div className="audience-list">
                      {contacts.length ? (
                        contacts.map((c) => (
                          <label key={c.id} className="checkbox-line">
                            <input
                              type="checkbox"
                              disabled={!c.consent || c.opted_out}
                              checked={
                                draft.contact_ids?.includes(c.id) || false
                              }
                              onChange={(e) =>
                                setDraft({
                                  ...draft,
                                  contact_ids: e.target.checked
                                    ? [...draft.contact_ids, c.id]
                                    : draft.contact_ids.filter(
                                        (id: string) => id !== c.id,
                                      ),
                                })
                              }
                            />
                            {c.name}
                            <small>
                              {c.phone}
                              {!c.consent || c.opted_out
                                ? " · not eligible"
                                : ""}
                            </small>
                          </label>
                        ))
                      ) : (
                        <p>Add contacts before creating a campaign.</p>
                      )}
                    </div>
                  </Field>
                  <p className="muted">
                    Calling windows use each contact’s timezone. Consent and
                    opt-out are rechecked before every attempt.
                  </p>
                </>
              )}
              <div className="info-panel">
                <Phone size={20} />
                <p>
                  {modal === "outbound"
                    ? "Submitting this form places a real call through your Twilio account."
                    : "Campaigns are saved as drafts. Start them from the campaign list when ready."}
                </p>
              </div>
            </>
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
        <div className="modal-content">
          <p>
            CSV headers: <strong>name, phone, consent, timezone</strong>.
            Additional columns become agent variables. Consent must explicitly
            be true, yes, or 1; missing consent defaults to false. Existing
            phone numbers are skipped.
          </p>
          <label className="button">
            <Upload size={16} />
            Choose CSV
            <input
              type="file"
              accept=".csv"
              hidden
              onChange={(e) => {
                const file = e.target.files?.[0];
                if (file)
                  void run(async () => {
                    const form = new FormData();
                    form.append("file", file);
                    const result = await api(
                      "/contacts/import-preview",
                      "POST",
                      form,
                    );
                    setDraft(result);
                  });
              }}
            />
          </label>
          {draft.contacts && (
            <>
              <p style={{ marginTop: 20 }}>
                {draft.contacts.length} valid contacts · {draft.errors.length}{" "}
                invalid rows
              </p>
              {draft.errors.map((e: Row) => (
                <p key={e.line} className="muted">
                  Line {e.line}: {e.message}
                </p>
              ))}
              <div className="audience-list">
                {draft.contacts.slice(0, 20).map((c: Row, i: number) => (
                  <div className="checkbox-line" key={i}>
                    {c.name}
                    <small>
                      {c.phone} · {c.consent ? "consented" : "no consent"}
                    </small>
                  </div>
                ))}
              </div>
              <div className="modal-footer">
                <Button onClick={() => setModal("")}>Cancel</Button>
                <Button
                  kind="primary"
                  disabled={
                    busy || !draft.contacts.length || draft.errors.length > 0
                  }
                  onClick={() =>
                    void run(async () => {
                      const result = await api(
                        "/contacts/import",
                        "POST",
                        draft.contacts,
                      );
                      saveDone(
                        `${result.imported} contacts imported; ${result.duplicates} existing numbers skipped`,
                      );
                    })
                  }
                >
                  Import {draft.contacts.length} contacts
                </Button>
              </div>
            </>
          )}
        </div>
      )}
      {modal === "documents" && (
        <div className="modal-content">
          <div className="document-actions">
            {canEdit && (
              <>
                <Button
                  onClick={() => {
                    setDraft({});
                    setModal("document");
                  }}
                >
                  <Plus size={16} />
                  Add text
                </Button>
                <label className="button">
                  <Upload size={16} />
                  Upload file
                  <input
                    type="file"
                    accept=".pdf,.txt,.md,.csv"
                    hidden
                    onChange={(e) => {
                      const file = e.target.files?.[0];
                      if (file)
                        void run(async () => {
                          const form = new FormData();
                          form.append("file", file);
                          await api(
                            `/collections/${selected!.id}/upload`,
                            "POST",
                            form,
                          );
                          setDocuments(
                            await api(`/collections/${selected!.id}/documents`),
                          );
                          setNotice("Document uploaded as draft");
                        });
                    }}
                  />
                </label>
              </>
            )}
            <span className="muted">PDF, TXT, MD, CSV · up to 5 MB</span>
          </div>
          {documents.length ? (
            documents.map((d) => (
              <div className="document-row" key={d.id}>
                <FileText size={22} />
                <div>
                  <strong>{d.title}</strong>
                  <p>{d.content.slice(0, 160)}…</p>
                  <small>
                    {d.content.length.toLocaleString()} characters ·{" "}
                    {date(d.created_at)}
                  </small>
                </div>
                <Badge value={d.status} />
                {isAdmin && (
                  <div className="row-actions">
                    {canEdit && selected?.embedding_connection_id && (
                      <button
                        disabled={busy}
                        onClick={() =>
                          void run(async () => {
                            const result = await api(
                              `/documents/${d.id}/index`,
                              "POST",
                            );
                            setNotice(
                              `${result.indexed_chunks} chunks indexed for semantic search`,
                            );
                          })
                        }
                      >
                        Index semantic
                      </button>
                    )}
                    {d.status === "draft" && (
                      <button
                        onClick={() =>
                          void run(async () => {
                            await api(`/documents/${d.id}/approve`, "POST");
                            setDocuments(
                              await api(
                                `/collections/${selected!.id}/documents`,
                              ),
                            );
                          })
                        }
                      >
                        Approve
                      </button>
                    )}
                    {d.status !== "archived" && (
                      <button
                        onClick={() =>
                          void run(async () => {
                            await api(`/documents/${d.id}/archive`, "POST");
                            setDocuments(
                              await api(
                                `/collections/${selected!.id}/documents`,
                              ),
                            );
                            refresh();
                          })
                        }
                      >
                        Archive
                      </button>
                    )}
                  </div>
                )}
              </div>
            ))
          ) : (
            <Empty title="This collection is ready for its first document">
              Add reference text or upload a file. Documents require approval
              before agents can use them.
            </Empty>
          )}
        </div>
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
      {modal === "audit" && (
        <div className="modal-content audit-list">
          {documents.map((d) => (
            <div key={d.id}>
              <Activity size={16} />
              <strong>{d.action}</strong>
              <span>{date(d.created_at)}</span>
            </div>
          ))}
        </div>
      )}
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
