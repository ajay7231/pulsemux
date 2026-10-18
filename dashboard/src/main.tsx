import React, { useEffect, useState, FormEvent, ReactNode } from "react";
import { createRoot } from "react-dom/client";
import {
  Activity,
  ArrowDownLeft,
  ArrowUpRight,
  ArrowRight,
  AudioLines,
  BookOpen,
  Bot,
  CalendarClock,
  Check,
  CheckCircle2,
  ChevronLeft,
  CircleHelp,
  ClipboardList,
  FileText,
  LayoutDashboard,
  LogOut,
  Megaphone,
  MoreHorizontal,
  Phone,
  Play,
  Plus,
  Search,
  Settings,
  ShieldCheck,
  SlidersHorizontal,
  Users,
  X,
  Zap,
  Plug,
  Pause,
  Upload,
  Clock3,
} from "lucide-react";
import "./styles.css";
import { AgentTest } from "./AgentTest";
import { ModelSelect } from "./ModelSelect";

type Row = Record<string, any>;
type Page =
  | "overview"
  | "agents"
  | "knowledge"
  | "connections"
  | "numbers"
  | "contacts"
  | "campaigns"
  | "calls"
  | "tasks"
  | "settings";
const NAV: [Page, string, typeof Activity][] = [
  ["overview", "Overview", LayoutDashboard],
  ["agents", "Agents", Bot],
  ["knowledge", "Knowledge", BookOpen],
  ["connections", "Connections", Plug],
  ["numbers", "Phone numbers", Phone],
  ["contacts", "Contacts", Users],
  ["campaigns", "Campaigns", Megaphone],
  ["calls", "Call history", AudioLines],
  ["tasks", "Staff tasks", ClipboardList],
  ["settings", "Settings", Settings],
];
const LABELS: Record<string, string> = Object.fromEntries(
  NAV.map(([key, label]) => [key, label]),
);
const VOICES: Record<string, string> = {
  af_bella: "Bella · American",
  af_sky: "Sky · American",
  am_adam: "Adam · American",
  am_michael: "Michael · American",
  bf_emma: "Emma · British",
  ...Object.fromEntries(
    [
      "thalia",
      "andromeda",
      "helena",
      "apollo",
      "arcas",
      "aries",
      "pandora",
      "draco",
    ].map((n) => [
      `aura-2-${n}-en`,
      `${n[0].toUpperCase() + n.slice(1)} · Aura-2`,
    ]),
  ),
};
const DEFAULT_CONFIG: Row = {
  template: "reception",
  department: "Reception",
  language: "en",
  greeting:
    "Hello, thank you for calling {{hospital_name}}. How can I help you today?",
  instructions:
    "Be warm and concise. Ask one question at a time. Use approved hospital information. Offer a staff callback when you cannot help.",
  tone: "warm",
  stt_engine: "deepgram",
  stt_connection_id: null,
  llm_connection_id: null,
  llm_model: "",
  tts_engine: "kokoro",
  tts_connection_id: null,
  voice_id: "af_bella",
  collection_ids: [],
  tools: ["request_callback", "record_outcome", "opt_out"],
  transfer_number: "",
  emergency_instructions:
    "For urgent symptoms, tell the caller to contact their local emergency service immediately and offer to connect hospital staff. Do not claim emergency services have been dispatched.",
  max_duration_seconds: 600,
  silence_timeout_seconds: 60,
  end_pause_ms: 800,
};
async function api(path: string, method = "GET", body?: unknown): Promise<any> {
  const response = await fetch("/api" + path, {
    method,
    credentials: "same-origin",
    headers:
      body instanceof FormData
        ? {}
        : body !== undefined
          ? { "Content-Type": "application/json" }
          : {},
    body:
      body instanceof FormData
        ? body
        : body !== undefined
          ? JSON.stringify(body)
          : undefined,
  });
  const result = await response
    .json()
    .catch(() => ({ detail: "The server returned an invalid response" }));
  if (!response.ok) {
    const detail = result.detail;
    throw new Error(
      typeof detail === "string"
        ? detail
        : Array.isArray(detail)
          ? detail
              .map((e: Row) => `${e.loc?.slice(1).join(".")}: ${e.msg}`)
              .join("; ")
          : "Request failed",
    );
  }
  return result;
}
const date = (value: number) =>
  new Date(value * 1000).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
function Badge({ value }: { value: string }) {
  return (
    <span
      className={
        "badge " +
        ([
          "published",
          "approved",
          "valid",
          "completed",
          "resolved",
          "in-progress",
        ].includes(value)
          ? "green"
          : ["failed", "revoked", "cancelled", "dispatch_unknown"].includes(
                value,
              )
            ? "red"
            : ["running", "ringing", "pending"].includes(value)
              ? "blue"
              : "neutral")
      }
    >
      <i />
      {value.replaceAll("_", " ").replaceAll("-", " ")}
    </span>
  );
}
function Button({
  children,
  onClick,
  kind = "",
  disabled = false,
  type = "button",
}: {
  children: ReactNode;
  onClick?: () => void;
  kind?: string;
  disabled?: boolean;
  type?: "button" | "submit";
}) {
  return (
    <button
      type={type}
      disabled={disabled}
      className={"button " + kind}
      onClick={onClick}
    >
      {children}
    </button>
  );
}
function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: ReactNode;
}) {
  const id = React.useId();
  const control =
    React.isValidElement(children) &&
    typeof children.type === "string" &&
    ["input", "textarea", "select"].includes(children.type)
      ? React.cloneElement(children as React.ReactElement<any>, {
          "aria-label": label,
          "aria-describedby": hint ? id : undefined,
        })
      : children;
  return (
    <label className="field">
      <span>{label}</span>
      {control}
      {hint && <small id={id}>{hint}</small>}
    </label>
  );
}

function Empty({
  title,
  children,
  action,
}: {
  title: string;
  children: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className="empty">
      <div className="empty-symbol">
        <AudioLines size={28} />
      </div>
      <h3>{title}</h3>
      <p>{children}</p>
      {action}
    </div>
  );
}
function Modal({
  title,
  subtitle,
  children,
  onClose,
  wide = false,
}: {
  title: string;
  subtitle?: string;
  children: ReactNode;
  onClose: () => void;
  wide?: boolean;
}) {
  const panel = React.useRef<HTMLElement>(null);
  const close = React.useRef(onClose);
  close.current = onClose;
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    const oldOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const focusable = () =>
      Array.from(
        panel.current?.querySelectorAll<HTMLElement>(
          "button:not(:disabled), input:not(:disabled), select:not(:disabled), textarea:not(:disabled), a[href], iframe",
        ) || [],
      );
    focusable()[0]?.focus();
    const listener = (event: KeyboardEvent) => {
      if (event.key === "Escape") close.current();
      if (event.key === "Tab") {
        const elements = focusable();
        const index = elements.indexOf(document.activeElement as HTMLElement);
        if (
          index < 0 ||
          (!event.shiftKey && index === elements.length - 1) ||
          (event.shiftKey && index === 0)
        ) {
          event.preventDefault();
          (event.shiftKey ? elements.at(-1) : elements[0])?.focus();
        }
      }
    };
    window.addEventListener("keydown", listener);
    return () => {
      window.removeEventListener("keydown", listener);
      document.body.style.overflow = oldOverflow;
      previous?.focus();
    };
  }, []);
  return (
    <div
      className="overlay"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <section
        ref={panel}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        className={"modal " + (wide ? "wide" : "")}
      >
        <header>
          <div>
            <h2>{title}</h2>
            {subtitle && <p>{subtitle}</p>}
          </div>
          <button
            className="icon-button"
            aria-label="Close dialog"
            onClick={onClose}
          >
            <X size={20} />
          </button>
        </header>
        {children}
      </section>
    </div>
  );
}
function TimezoneSelect({
  zones,
  ...props
}: { zones: string[] } & React.SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select aria-label="Timezone" required {...props}>
      {zones.map((zone) => (
        <option key={zone} value={zone}>
          {zone.replaceAll("_", " ")}
        </option>
      ))}
    </select>
  );
}
export function App() {
  const [loading, setLoading] = useState(true),
    [session, setSession] = useState<Row | null>(null),
    [setup, setSetup] = useState(false),
    [setupAvailable, setSetupAvailable] = useState(false),
    [timezones, setTimezones] = useState<string[]>(["Asia/Kolkata", "UTC"]),
    [setupTokenRequired, setSetupTokenRequired] = useState(false),
    [page, setPage] = useState<Page>("overview"),
    [data, setData] = useState<Row[]>([]),
    [overview, setOverview] = useState<Row>({}),
    [busy, setBusy] = useState(false),
    [notice, setNotice] = useState(""),
    [error, setError] = useState(""),
    [search, setSearch] = useState(""),
    [modal, setModal] = useState(""),
    [selected, setSelected] = useState<Row | null>(null),
    [editor, setEditor] = useState<Row | null>(null),
    [agentTab, setAgentTab] = useState("Identity"),
    [connections, setConnections] = useState<Row[]>([]),
    [collections, setCollections] = useState<Row[]>([]),
    [agents, setAgents] = useState<Row[]>([]),
    [contacts, setContacts] = useState<Row[]>([]),
    [numbers, setNumbers] = useState<Row[]>([]),
    [templates, setTemplates] = useState<Row[]>([]),
    [documents, setDocuments] = useState<Row[]>([]),
    [draft, setDraft] = useState<Row>({}),
    [simulator, setSimulator] = useState<Row | null>(null),
    [call, setCall] = useState<Row | null>(null),
    [refreshKey, setRefreshKey] = useState(0);
  const canEdit = session?.user.role !== "viewer",
    isAdmin = session?.user.role === "admin";
  const refresh = () => setRefreshKey((k) => k + 1);
  const run = async (fn: () => Promise<void>) => {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await fn();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  useEffect(() => {
    (async () => {
      try {
        const info = await api("/bootstrap");
        setSetupAvailable(info.setup_required);
        setSetup(info.setup_required && window.location.hash !== "#login");
        setSetupTokenRequired(info.setup_token_required);
        if (!info.setup_required) {
          try {
            setSession(await api("/me"));
          } catch {}
        }
      } catch (e) {
        setError((e as Error).message);
      } finally {
        setLoading(false);
      }
    })();
  }, []);
  useEffect(() => {
    api("/timezones")
      .then((zones) => {
        if (Array.isArray(zones) && zones.length) setTimezones(zones);
      })
      .catch(() => {});
  }, []);
  useEffect(() => {
    const changeAuth = () => {
      setSetup(setupAvailable && window.location.hash !== "#login");
      setError("");
      setDraft((prev) => ({ ...prev, password: "", setup_token: "" }));
    };
    window.addEventListener("hashchange", changeAuth);
    return () => window.removeEventListener("hashchange", changeAuth);
  }, [setupAvailable]);
  useEffect(() => {
    if (!session) return;
    let live = true;
    setLoading(true);
    setSearch("");
    (async () => {
      try {
        const [c, k, a, t, n, people] = await Promise.all([
          api("/connections"),
          api("/collections"),
          api("/agents"),
          api("/templates"),
          api("/numbers"),
          api("/contacts"),
        ]);
        if (!live) return;
        setConnections(c);
        setCollections(k);
        setAgents(a);
        setTemplates(t);
        setNumbers(n);
        setContacts(people);
        const endpoints: Record<Page, string> = {
          overview: "/overview",
          agents: "/agents",
          knowledge: "/collections",
          connections: "/connections",
          numbers: "/numbers",
          contacts: "/contacts",
          campaigns: "/campaigns",
          calls: "/calls",
          tasks: "/tasks",
          settings: isAdmin ? "/users" : "/me",
        };
        const result = await api(endpoints[page]);
        if (!live) return;
        if (page === "overview") setOverview(result);
        else setData(Array.isArray(result) ? result : []);
      } catch (e) {
        if (live) setError((e as Error).message);
      } finally {
        if (live) setLoading(false);
      }
    })();
    return () => {
      live = false;
    };
  }, [session, page, refreshKey, isAdmin]);
  useEffect(() => {
    if (!notice) return;
    const timer = setTimeout(() => setNotice(""), 7000);
    return () => clearTimeout(timer);
  }, [notice]);
  function navigate(next: Page) {
    setPage(next);
    setSimulator(null);
    setEditor(null);
    setError("");
    setModal("");
    setSelected(null);
  }
  function newAgent(template?: Row) {
    setEditor({
      name: "",
      description: "",
      config: {
        ...structuredClone(DEFAULT_CONFIG),
        ...(template
          ? {
              template: template.id,
              greeting: template.greeting,
              instructions: template.instructions,
            }
          : {}),
      },
    });
    setAgentTab("Identity");
    setModal("");
  }
  const filtered = data.filter((row) =>
    JSON.stringify(row).toLowerCase().includes(search.toLowerCase()),
  );
  function startModal(name: string, initial: Row = {}) {
    setDraft(initial);
    setModal(name);
    setError("");
  }
  const formSubmit = (fn: () => Promise<void>) => (event: FormEvent) => {
    event.preventDefault();
    void run(fn);
  };
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
  const saveDone = (message: string) => {
    setModal("");
    refresh();
    setNotice(message);
  };
  if (!session)
    return (
      <div className="auth-page">
        <div className="auth-brand">
          <div className="brand-mark">
            <Activity />
          </div>
          PulseMux<span>CLINICAL VOICE OPERATIONS</span>
        </div>
        <section className="auth-card">
          <div className="eyebrow">YOUR HOSPITAL. YOUR AGENTS.</div>
          <h1>
            {loading
              ? "Connecting…"
              : setup
                ? "A better way to stay connected."
                : "Welcome back."}
          </h1>
          <p>
            {setup
              ? "Create your workspace to build, test, and manage your hospital’s voice agents."
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
                setSession(
                  await api(setup ? "/setup" : "/login", "POST", body),
                );
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
                  Already have a workspace? <a href="#login">Sign in</a>
                </>
              ) : (
                <>
                  Use the email and password registered with your hospital on
                  this server.
                  {setupAvailable && (
                    <>
                      <br />
                      <a href="#setup">Create a workspace</a>
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
        <span className="auth-bottom">Built for thoughtful conversations.</span>
      </div>
    );
  const config = editor?.config || {};
  const unsaved =
    !!editor?.id &&
    editor._savedFingerprint !==
      JSON.stringify({
        name: editor.name,
        description: editor.description,
        config: editor.config,
      });
  function cf(key: string, value: any) {
    setEditor((prev) =>
      prev ? { ...prev, config: { ...prev.config, [key]: value } } : prev,
    );
  }
  const configField = (
    key: string,
    label: string,
    hint?: string,
    area = false,
  ) => (
    <Field label={label} hint={hint}>
      {area ? (
        <textarea
          rows={key === "instructions" ? 8 : 4}
          value={config[key] ?? ""}
          onChange={(e) => cf(key, e.target.value)}
        />
      ) : (
        <input
          value={config[key] ?? ""}
          onChange={(e) => cf(key, e.target.value)}
        />
      )}
    </Field>
  );
  const connectionSelect = (
    key: string,
    provider: string | string[],
    label: string,
  ) => {
    const providers = Array.isArray(provider) ? provider : [provider];
    const available = connections.filter(
      (c) => c.active && providers.includes(c.provider),
    );
    const missing = config[key] && !available.some((c) => c.id === config[key]);
    return (
      <div className="connection-picker">
        <Field
          label={label}
          hint={
            !available.length
              ? `Add ${providers.map((p) => (p === "openai" ? "OpenAI" : p[0].toUpperCase() + p.slice(1))).join(" or ")} credentials to connect this part of your agent.`
              : undefined
          }
        >
          <select
            value={config[key] || ""}
            disabled={!available.length}
            onChange={(e) => {
              cf(key, e.target.value || null);
              if (key === "llm_connection_id") cf("llm_model", "");
            }}
          >
            <option value="">
              {available.length
                ? "Choose a saved connection"
                : "No compatible connections yet"}
            </option>
            {missing && (
              <option value={config[key]} disabled>
                Previous connection unavailable
              </option>
            )}
            {available.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name} · {c.provider === "openai" ? "OpenAI" : c.provider} ·{" "}
                {c.test_status === "valid"
                  ? "Verified"
                  : c.test_status === "failed"
                    ? "Check credentials"
                    : "Not verified"}
              </option>
            ))}
          </select>
        </Field>
        {missing && (
          <p className="field-error">
            This connection is unavailable. Select or add a replacement.
          </p>
        )}
        {isAdmin ? (
          <button
            type="button"
            className="text-button"
            onClick={() =>
              startModal("connection", {
                provider: providers[0],
                name: "",
                _agentField: key,
                _providers: providers,
              })
            }
          >
            <Plus size={14} /> Add connection
          </button>
        ) : (
          <p className="muted">
            Ask a workspace administrator to add credentials.
          </p>
        )}
      </div>
    );
  };
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <a
          className="brand"
          href="#"
          onClick={(e) => {
            e.preventDefault();
            navigate("overview");
          }}
        >
          <div className="brand-mark">
            <Activity size={22} />
          </div>
          <span>
            PulseMux<small>VOICE OPERATIONS</small>
          </span>
        </a>
        <div className="workspace">
          <div className="workspace-avatar">
            {session.workspace.name.slice(0, 2).toUpperCase()}
          </div>
          <div>
            <strong>{session.workspace.name}</strong>
            <small>Hospital workspace</small>
          </div>
          <span className="online-dot" />
        </div>
        <div className="nav-label">WORKSPACE</div>
        <nav>
          {NAV.map(([key, label, Icon]) => (
            <button
              key={key}
              className={page === key ? "active" : ""}
              onClick={() => navigate(key)}
            >
              <Icon size={18} />
              {label}
              {key === "tasks" && overview.open_tasks > 0 && (
                <span className="nav-count">{overview.open_tasks}</span>
              )}
            </button>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <div className="hosted">
            <span className="online-dot" />
            Self-hosted workspace
            <small>Your infrastructure. Your control.</small>
          </div>
          <button
            className="profile"
            onClick={() =>
              void run(async () => {
                await api("/logout", "POST");
                setSession(null);
                setData([]);
                setEditor(null);
                setSimulator(null);
              })
            }
          >
            <span className="profile-avatar">{session.user.name[0]}</span>
            <span>
              <strong>{session.user.name}</strong>
              <small>{session.user.role}</small>
            </span>
            <LogOut size={16} />
          </button>
        </div>
      </aside>
      <div className="main-shell">
        <header className="topbar">
          <span>
            Workspace <span className="slash">/</span>{" "}
            <strong>{LABELS[page]}</strong>
            {editor && (
              <>
                <span className="slash">/</span>
                <span>{editor.name || "New agent"}</span>
              </>
            )}
          </span>
          <div>
            <span className="private-pill">
              <ShieldCheck size={14} />
              Private workspace
            </span>
            <button
              className="icon-button"
              aria-label="Help"
              onClick={() => startModal("help")}
            >
              <CircleHelp size={19} />
            </button>
          </div>
        </header>
        <main>
          {error && (
            <div className="alert error" role="alert">
              {error}
              <button aria-label="Dismiss error" onClick={() => setError("")}>
                <X size={16} />
              </button>
            </div>
          )}
          {notice && (
            <div className="alert success" role="status">
              <CheckCircle2 size={17} />
              {notice}
            </div>
          )}
          {simulator ? (
            <AgentTest
              agent={simulator as any}
              voice={
                VOICES[simulator.config.voice_id] || simulator.config.voice_id
              }
              onClose={() => {
                const id = simulator.id;
                setSimulator(null);
                void run(async () => {
                  const updated = await api("/agents/" + id);
                  setEditor({
                    ...updated,
                    _savedFingerprint: JSON.stringify({
                      name: updated.name,
                      description: updated.description,
                      config: updated.config,
                    }),
                  });
                  refresh();
                });
              }}
            />
          ) : editor ? (
            <>
              <div className="page-heading">
                <div>
                  <button className="back-link" onClick={() => setEditor(null)}>
                    <ChevronLeft size={15} />
                    All agents
                  </button>
                  <h1>
                    {editor.id ? editor.name : "Create an agent"}{" "}
                    {editor.id && <Badge value={editor.status} />}
                  </h1>
                  <p>
                    Shape the conversation. Test it before your patients hear
                    it.
                  </p>
                </div>
                <div className="actions">
                  <Button
                    disabled={busy || !canEdit}
                    onClick={() =>
                      void run(async () => {
                        const saved = await api(
                          "/agents" + (editor.id ? "/" + editor.id : ""),
                          editor.id ? "PUT" : "POST",
                          {
                            name: editor.name,
                            description: editor.description,
                            config: editor.config,
                            ...(editor.id ? { revision: editor.revision } : {}),
                          },
                        );
                        setEditor({
                          ...saved,
                          _savedFingerprint: JSON.stringify({
                            name: saved.name,
                            description: saved.description,
                            config: saved.config,
                          }),
                        });
                        refresh();
                        setNotice(
                          "Draft saved. Test this revision before publishing.",
                        );
                      })
                    }
                  >
                    Save draft
                  </Button>
                  <Button
                    disabled={busy || !editor.id || unsaved}
                    onClick={() => {
                      if (
                        !config.stt_connection_id ||
                        !config.llm_connection_id ||
                        !config.llm_model ||
                        (config.tts_engine === "deepgram" &&
                          !config.tts_connection_id)
                      ) {
                        setAgentTab("Voice & models");
                        setError(
                          "Complete the speech recognition connection, language model, and voice settings before testing.",
                        );
                        return;
                      }
                      void run(async () => {
                        await api("/agents/" + editor.id + "/validate", "POST");
                        setSimulator({
                          id: editor.id,
                          draft: true,
                          name: editor.name,
                          revision: editor.revision,
                          config: structuredClone(editor.config),
                        });
                      });
                    }}
                  >
                    <Play size={15} />
                    Test agent
                  </Button>
                  <Button
                    kind="primary"
                    disabled={busy || !editor.id || !isAdmin || unsaved}
                    onClick={() =>
                      void run(async () => {
                        const saved = await api(
                          `/agents/${editor.id}/publish`,
                          "POST",
                        );
                        setEditor({
                          ...saved,
                          _savedFingerprint: JSON.stringify({
                            name: saved.name,
                            description: saved.description,
                            config: saved.config,
                          }),
                        });
                        refresh();
                        setNotice(
                          "Agent published. New calls will use this version.",
                        );
                      })
                    }
                  >
                    <Zap size={15} />
                    Publish agent
                  </Button>
                </div>
              </div>
              <div className="agent-workspace">
                <aside className="editor-nav">
                  {[
                    "Identity",
                    "Behavior",
                    "Voice & models",
                    "Knowledge",
                    "Actions & safety",
                    "Call settings",
                  ].map((tab, i) => (
                    <button
                      key={tab}
                      className={agentTab === tab ? "selected" : ""}
                      onClick={() => setAgentTab(tab)}
                    >
                      <span>{String(i + 1).padStart(2, "0")}</span>
                      {tab}
                    </button>
                  ))}
                  <div className="editor-note">
                    <ShieldCheck size={20} />
                    <strong>Changes stay in draft</strong>
                    <p>
                      Published versions remain fixed for active calls. Save and
                      test before publishing.
                    </p>
                    {editor.tested_revision === editor.revision &&
                      editor.id && <Badge value="tested" />}
                  </div>
                </aside>
                <section className="card editor-card">
                  <div className="section-heading">
                    <div>
                      <span className="eyebrow">AGENT CONFIGURATION</span>
                      <h2>{agentTab}</h2>
                    </div>
                    <SlidersHorizontal size={20} />
                  </div>
                  {agentTab === "Identity" && (
                    <>
                      <div className="form-grid">
                        <Field label="Agent name">
                          <input
                            value={editor.name}
                            placeholder="e.g. Appointment concierge"
                            onChange={(e) =>
                              setEditor({ ...editor, name: e.target.value })
                            }
                          />
                        </Field>
                        {configField("department", "Department")}
                      </div>
                      <Field label="Description">
                        <textarea
                          rows={3}
                          value={editor.description}
                          placeholder="What will this agent help your team with?"
                          onChange={(e) =>
                            setEditor({
                              ...editor,
                              description: e.target.value,
                            })
                          }
                        />
                      </Field>
                      <Field label="Workflow template">
                        <select
                          value={config.template}
                          onChange={(e) => {
                            const t = templates.find(
                              (t) => t.id === e.target.value,
                            )!;
                            setEditor({
                              ...editor,
                              config: {
                                ...config,
                                template: t.id,
                                greeting: t.greeting,
                                instructions: t.instructions,
                              },
                            });
                          }}
                        >
                          {templates.map((t) => (
                            <option key={t.id} value={t.id}>
                              {t.name}
                            </option>
                          ))}
                        </select>
                      </Field>
                      <div className="info-panel">
                        <CalendarClock size={21} />
                        <p>
                          {
                            templates.find((t) => t.id === config.template)
                              ?.description
                          }{" "}
                          Templates provide a starting point. Review the
                          instructions for your hospital.
                        </p>
                      </div>
                    </>
                  )}
                  {agentTab === "Behavior" && (
                    <>
                      {configField(
                        "greeting",
                        "Opening greeting",
                        "Variables use double braces: {{hospital_name}}, {{patient_name}}, {{appointment_date}}.",
                        true,
                      )}
                      {configField(
                        "instructions",
                        "Conversation instructions",
                        "Define what to ask, what information to collect, and when to involve staff.",
                        true,
                      )}
                      <Field label="Tone">
                        <select
                          value={config.tone}
                          onChange={(e) => cf("tone", e.target.value)}
                        >
                          {["warm", "professional", "calm"].map((v) => (
                            <option key={v}>{v}</option>
                          ))}
                        </select>
                      </Field>
                      <div className="info-panel">
                        <ShieldCheck size={20} />
                        <p>
                          Operating rules always prevent invented bookings,
                          prescriptions, credential disclosure, and unsupported
                          clinical claims.
                        </p>
                      </div>
                    </>
                  )}
                  {agentTab === "Voice & models" && (
                    <>
                      <h3>Understanding the caller</h3>
                      <div className="form-grid">
                        <Field label="Speech recognition">
                          <select
                            value={config.stt_engine}
                            onChange={(e) => {
                              cf("stt_engine", e.target.value);
                              cf("stt_connection_id", null);
                            }}
                          >
                            <option value="deepgram">Deepgram Nova-3</option>
                            <option value="groq">Groq Whisper Turbo</option>
                          </select>
                        </Field>
                        {connectionSelect(
                          "stt_connection_id",
                          config.stt_engine,
                          "ASR connection",
                        )}
                      </div>
                      <hr />
                      <h3>Generating a response</h3>
                      {connectionSelect(
                        "llm_connection_id",
                        ["groq", "openai"],
                        "Language model connection",
                      )}
                      <ModelSelect
                        connectionId={config.llm_connection_id}
                        revision={
                          connections.find(
                            (c) => c.id === config.llm_connection_id,
                          )?.revision
                        }
                        value={config.llm_model || ""}
                        onChange={(value) => cf("llm_model", value)}
                      />
                      <hr />
                      <h3>Speaking to the caller</h3>
                      <div className="form-grid">
                        <Field label="Voice provider">
                          <select
                            value={config.tts_engine}
                            onChange={(e) => {
                              setEditor({
                                ...editor,
                                config: {
                                  ...config,
                                  tts_engine: e.target.value,
                                  voice_id:
                                    e.target.value === "kokoro"
                                      ? "af_bella"
                                      : "aura-2-thalia-en",
                                  tts_connection_id: null,
                                },
                              });
                            }}
                          >
                            <option value="kokoro">Kokoro · Local</option>
                            <option value="deepgram">Deepgram Aura-2</option>
                          </select>
                        </Field>
                        <Field label="Voice">
                          <select
                            value={config.voice_id}
                            onChange={(e) => cf("voice_id", e.target.value)}
                          >
                            {Object.entries(VOICES)
                              .filter(([key]) =>
                                config.tts_engine === "deepgram"
                                  ? key.startsWith("aura")
                                  : !key.startsWith("aura"),
                              )
                              .map(([key, label]) => (
                                <option key={key} value={key}>
                                  {label}
                                </option>
                              ))}
                          </select>
                        </Field>
                      </div>
                      {config.tts_engine === "deepgram" &&
                        connectionSelect(
                          "tts_connection_id",
                          "deepgram",
                          "TTS connection",
                        )}
                      <p className="muted">
                        Credentials are managed in Connections. Only saved
                        connections from this workspace can be used.
                      </p>
                    </>
                  )}
                  {agentTab === "Knowledge" && (
                    <>
                      <p className="muted">
                        Attach collections this agent can reference. Only
                        approved, unexpired documents are included when
                        publishing.
                      </p>
                      {collections.length ? (
                        collections.map((c) => (
                          <label className="check-card" key={c.id}>
                            <input
                              type="checkbox"
                              checked={config.collection_ids.includes(c.id)}
                              onChange={(e) =>
                                cf(
                                  "collection_ids",
                                  e.target.checked
                                    ? [...config.collection_ids, c.id]
                                    : config.collection_ids.filter(
                                        (id: string) => id !== c.id,
                                      ),
                                )
                              }
                            />
                            <BookOpen size={20} />
                            <div>
                              <strong>{c.name}</strong>
                              <p>
                                {c.description ||
                                  "Hospital reference collection"}
                              </p>
                            </div>
                          </label>
                        ))
                      ) : (
                        <Empty title="No knowledge collections yet">
                          Create a collection in Knowledge, add documents, and
                          have an administrator approve them.
                        </Empty>
                      )}
                    </>
                  )}
                  {agentTab === "Actions & safety" && (
                    <>
                      {[
                        ["request_callback", "Create staff callback requests"],
                        ["record_outcome", "Record appointment attendance"],
                        ["opt_out", "Respect automated-call opt-out requests"],
                        ["transfer", "Transfer callers to hospital staff"],
                      ].map(([key, label]) => (
                        <label className="check-card" key={key}>
                          <input
                            type="checkbox"
                            checked={config.tools.includes(key)}
                            onChange={(e) =>
                              cf(
                                "tools",
                                e.target.checked
                                  ? [...config.tools, key]
                                  : config.tools.filter(
                                      (v: string) => v !== key,
                                    ),
                              )
                            }
                          />
                          <div>
                            <strong>{label}</strong>
                          </div>
                        </label>
                      ))}
                      {config.tools.includes("transfer") &&
                        configField(
                          "transfer_number",
                          "Staff transfer number",
                          "Include country code, e.g. +919876543210.",
                        )}
                      {configField(
                        "emergency_instructions",
                        "Urgent-symptom escalation instructions",
                        "Have an authorized clinical lead review these instructions before publishing.",
                        true,
                      )}
                      <div className="info-panel">
                        <ClipboardList size={20} />
                        <p>
                          Appointment changes create staff requests. This
                          release does not change an external hospital
                          scheduling system.
                        </p>
                      </div>
                    </>
                  )}
                  {agentTab === "Call settings" && (
                    <>
                      <div className="form-grid">
                        {[
                          [
                            "max_duration_seconds",
                            "Maximum call duration (seconds)",
                          ],
                          [
                            "silence_timeout_seconds",
                            "Inactivity timeout (seconds)",
                          ],
                          ["end_pause_ms", "End-of-turn pause (milliseconds)"],
                        ].map(([key, label]) => (
                          <Field key={key} label={label}>
                            <input
                              type="number"
                              value={config[key]}
                              onChange={(e) => cf(key, Number(e.target.value))}
                            />
                          </Field>
                        ))}
                      </div>
                      <div className="info-panel">
                        <AudioLines size={20} />
                        <p>
                          Continuous listening, interruption handling, automatic
                          goodbye, and background-noise suppression remain
                          available in the simulator.
                        </p>
                      </div>
                    </>
                  )}
                </section>
              </div>
            </>
          ) : (
            <>
              <div className="page-heading">
                <div>
                  <div className="eyebrow">
                    {page === "overview"
                      ? "YOUR OPERATIONS, CONNECTED"
                      : "WORKSPACE / " + LABELS[page].toUpperCase()}
                  </div>
                  <h1>
                    {page === "overview"
                      ? `Welcome back, ${session.user.name.split(" ")[0]}.`
                      : LABELS[page]}
                  </h1>
                  <p>
                    {
                      {
                        overview:
                          "A clear view of every conversation and the work that follows.",
                        agents:
                          "Build thoughtful voice agents for the moments that matter.",
                        knowledge:
                          "Give your agents reliable, approved hospital information.",
                        connections:
                          "Bring your providers. Keep credentials secure and in your control.",
                        numbers:
                          "Connect your phone numbers to the right hospital agent.",
                        contacts:
                          "Manage the people you contact and their calling preferences.",
                        campaigns:
                          "Reach patients at the right time, with the right conversation.",
                        calls:
                          "Follow every conversation from the first hello to the next step.",
                        tasks:
                          "A shared queue for the conversations that need a human.",
                        settings: "Manage your workspace, team, and access.",
                      }[page]
                    }
                  </p>
                </div>
                <div className="actions">
                  {canEdit &&
                    (
                      [
                        "agents",
                        "knowledge",
                        "connections",
                        "numbers",
                        "contacts",
                        "campaigns",
                      ] as Page[]
                    ).includes(page) && (
                      <Button
                        kind="primary"
                        disabled={
                          busy ||
                          (["connections", "numbers"].includes(page) &&
                            !isAdmin)
                        }
                        onClick={() => {
                          if (page === "agents") startModal("templates");
                          else if (page === "knowledge")
                            startModal("collection");
                          else if (page === "connections")
                            startModal("connection", { provider: "deepgram" });
                          else if (page === "numbers") startModal("number");
                          else if (page === "contacts")
                            startModal("contact", {
                              consent: false,
                              timezone: session.workspace.timezone,
                              variables: "{}",
                            });
                          else
                            startModal("campaign", {
                              contact_ids: [],
                              starts_at: new Date(
                                Date.now() +
                                  60000 -
                                  new Date().getTimezoneOffset() * 60000,
                              )
                                .toISOString()
                                .slice(0, 16),
                              window_start: 9,
                              window_end: 18,
                              concurrency: 2,
                              max_attempts: 2,
                              retry_minutes: 60,
                            });
                        }}
                      >
                        <Plus size={17} />
                        {
                          (
                            {
                              agents: "Create agent",
                              knowledge: "New collection",
                              connections: "Add connection",
                              numbers: "Assign number",
                              contacts: "Add contact",
                              campaigns: "New campaign",
                            } as Row
                          )[page]
                        }
                      </Button>
                    )}
                  {page === "contacts" && canEdit && (
                    <Button onClick={() => startModal("import")}>
                      <Upload size={16} />
                      Import CSV
                    </Button>
                  )}
                  {page === "calls" && canEdit && (
                    <Button onClick={() => startModal("outbound")}>
                      <Phone size={16} />
                      Place a call
                    </Button>
                  )}
                </div>
              </div>
              {loading ? (
                <div className="loading">
                  <span />
                  Loading your workspace…
                </div>
              ) : page === "overview" ? (
                <>
                  <section className="welcome-panel">
                    <div>
                      <span className="hero-tag">
                        <span className="online-dot" />
                        DESIGNED AROUND YOUR PATIENTS
                      </span>
                      <h2>
                        Care starts with
                        <br />a conversation.
                      </h2>
                      <p>
                        Let your agents handle the routine.
                        <br />
                        Give your team more time for the people who need them.
                      </p>
                      <Button kind="primary" onClick={() => navigate("agents")}>
                        Meet your agents
                        <ArrowRight size={16} />
                      </Button>
                    </div>
                    <div className="conversation-art" aria-hidden="true">
                      <div className="art-orbit orbit-one" />
                      <div className="art-orbit orbit-two" />
                      <div className="art-core">
                        <AudioLines size={48} />
                      </div>
                      <div className="art-chip chip-one">
                        <CalendarClock size={18} />
                        <span>Appointments, connected.</span>
                        <CheckCircle2 size={16} />
                      </div>
                      <div className="art-chip chip-two">
                        <Activity size={18} />
                        <span>A little more peace of mind.</span>
                      </div>
                      <span className="art-dot dot-one" />
                      <span className="art-dot dot-two" />
                    </div>
                  </section>
                  <div className="stats-grid">
                    {[
                      [
                        Bot,
                        "Total agents",
                        overview.agents || 0,
                        "Configured in this workspace",
                      ],
                      [
                        AudioLines,
                        "Conversations",
                        overview.calls || 0,
                        `${overview.active_calls || 0} calls active now`,
                      ],
                      [
                        Megaphone,
                        "Campaigns",
                        overview.campaigns || 0,
                        "Patient outreach workflows",
                      ],
                      [
                        ClipboardList,
                        "Needs a human",
                        overview.open_tasks || 0,
                        "Open staff follow-ups",
                      ],
                    ].map(([Icon, label, value, hint], i) => {
                      const I = Icon as typeof Bot;
                      return (
                        <div className="stat card" key={i}>
                          <div>
                            <span>{label as string}</span>
                            <I size={18} />
                          </div>
                          <strong>{value as number}</strong>
                          <small>{hint as string}</small>
                        </div>
                      );
                    })}
                  </div>
                  <div className="overview-columns">
                    <section className="card">
                      <div className="section-heading">
                        <div>
                          <h2>Recent conversations</h2>
                          <p>Every call leaves a clear next step.</p>
                        </div>
                        <button
                          className="text-button"
                          onClick={() => navigate("calls")}
                        >
                          View all
                          <ArrowRight size={14} />
                        </button>
                      </div>
                      {overview.recent_calls?.length ? (
                        <CallTable
                          rows={overview.recent_calls}
                          agents={agents}
                          open={(id) =>
                            void run(async () =>
                              setCall(await api("/calls/" + id)),
                            )
                          }
                        />
                      ) : (
                        <Empty title="Your first conversation starts here">
                          Create an agent, connect a provider, and test it in
                          the simulator.
                          <Button onClick={() => navigate("agents")}>
                            Set up an agent
                            <ArrowRight size={15} />
                          </Button>
                        </Empty>
                      )}
                    </section>
                    <section className="card getting-started">
                      <span className="eyebrow">MAKE IT YOURS</span>
                      <h2>
                        A workspace ready
                        <br />
                        for your team.
                      </h2>
                      {[
                        [
                          connections.length > 0,
                          "Connect your providers",
                          "connections",
                        ],
                        [
                          agents.length > 0,
                          "Create your first agent",
                          "agents",
                        ],
                        [
                          collections.length > 0,
                          "Add hospital knowledge",
                          "knowledge",
                        ],
                        [
                          numbers.length > 0,
                          "Connect a phone number",
                          "numbers",
                        ],
                      ].map(([done, label, target], i) => (
                        <button
                          key={i}
                          onClick={() => navigate(target as Page)}
                        >
                          <span className={done ? "step-done" : "step-circle"}>
                            {done ? <Check size={14} /> : i + 1}
                          </span>
                          <span>{label as string}</span>
                          <ArrowRight size={14} />
                        </button>
                      ))}
                      <div className="quiet-note">
                        <ShieldCheck size={17} />
                        Your credentials stay encrypted.
                        <br />
                        Your workspace stays yours.
                      </div>
                    </section>
                  </div>
                </>
              ) : (
                <>
                  {page !== "settings" && (
                    <div className="list-toolbar">
                      <div className="search">
                        <Search size={16} />
                        <input
                          aria-label="Search records"
                          placeholder={`Search ${LABELS[page].toLowerCase()}…`}
                          value={search}
                          onChange={(e) => setSearch(e.target.value)}
                        />
                      </div>
                      <span>
                        {filtered.length}{" "}
                        {page === "knowledge"
                          ? "collections"
                          : LABELS[page].toLowerCase()}
                      </span>
                      <button
                        className="icon-button"
                        aria-label="Refresh records"
                        onClick={refresh}
                      >
                        <Activity size={17} />
                      </button>
                    </div>
                  )}
                  {page === "agents" &&
                    (filtered.length ? (
                      <div className="agent-grid">
                        {filtered.map((a) => (
                          <article className="card agent-card" key={a.id}>
                            <div className="agent-card-top">
                              <div className="agent-symbol">
                                <Bot size={25} />
                              </div>
                              <Badge value={a.status} />
                            </div>
                            <h2>{a.name}</h2>
                            <p>
                              {a.description ||
                                templates.find(
                                  (t) => t.id === a.config.template,
                                )?.description}
                            </p>
                            <div className="agent-meta">
                              <span>
                                <AudioLines size={14} />
                                {a.config.tts_engine === "deepgram"
                                  ? "Deepgram Aura-2"
                                  : "Kokoro voice"}
                              </span>
                              <span>{a.config.department}</span>
                            </div>
                            <div className="agent-card-bottom">
                              <span>Draft revision {a.revision}</span>
                              <button
                                className="text-button"
                                onClick={() => {
                                  setEditor({
                                    ...a,
                                    _savedFingerprint: JSON.stringify({
                                      name: a.name,
                                      description: a.description,
                                      config: a.config,
                                    }),
                                  });
                                  setAgentTab("Identity");
                                }}
                              >
                                Configure
                                <ArrowRight size={15} />
                              </button>
                            </div>
                          </article>
                        ))}
                      </div>
                    ) : (
                      <section className="card">
                        <Empty
                          title="Meet your next team member"
                          action={
                            <Button
                              kind="primary"
                              onClick={() => startModal("templates")}
                            >
                              <Plus size={16} />
                              Create your first agent
                            </Button>
                          }
                        >
                          Start with a hospital workflow, then make its voice
                          and behavior your own.
                        </Empty>
                      </section>
                    ))}
                  {page === "connections" && (
                    <section className="card">
                      {filtered.length ? (
                        <div className="table-scroll">
                          <table>
                            <thead>
                              <tr>
                                <th>Connection</th>
                                <th>Provider</th>
                                <th>Status</th>
                                <th>Last checked</th>
                                <th />
                              </tr>
                            </thead>
                            <tbody>
                              {filtered.map((c) => (
                                <tr key={c.id}>
                                  <td>
                                    <strong>{c.name}</strong>
                                    <small>
                                      Credential revision {c.revision} ·
                                      encrypted
                                    </small>
                                  </td>
                                  <td className="capitalize">{c.provider}</td>
                                  <td>
                                    <Badge
                                      value={
                                        !c.active ? "revoked" : c.test_status
                                      }
                                    />
                                  </td>
                                  <td>
                                    {c.tested_at
                                      ? date(c.tested_at)
                                      : "Not tested"}
                                  </td>
                                  <td>
                                    <div className="row-actions">
                                      {isAdmin && (
                                        <>
                                          <button
                                            onClick={() =>
                                              void run(async () => {
                                                const result = await api(
                                                  `/connections/${c.id}/test`,
                                                  "POST",
                                                );
                                                refresh();
                                                setNotice(result.message);
                                              })
                                            }
                                            disabled={busy || !c.active}
                                          >
                                            Test
                                          </button>
                                          <button
                                            onClick={() =>
                                              startModal("connection", {
                                                id: c.id,
                                                name: c.name,
                                                provider: c.provider,
                                              })
                                            }
                                          >
                                            Rotate
                                          </button>
                                          <button
                                            className="danger-text"
                                            onClick={() =>
                                              void run(async () => {
                                                await api(
                                                  `/connections/${c.id}/revoke`,
                                                  "POST",
                                                );
                                                refresh();
                                                setNotice("Connection revoked");
                                              })
                                            }
                                            disabled={busy || !c.active}
                                          >
                                            Revoke
                                          </button>
                                        </>
                                      )}
                                    </div>
                                  </td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      ) : (
                        <Empty
                          title="Your providers, connected"
                          action={
                            isAdmin ? (
                              <Button
                                onClick={() =>
                                  startModal("connection", {
                                    provider: "deepgram",
                                  })
                                }
                              >
                                <Plus size={16} />
                                Add a connection
                              </Button>
                            ) : undefined
                          }
                        >
                          Save Twilio, Deepgram, Groq, or OpenAI credentials.
                          Keys are encrypted and never returned to the browser.
                        </Empty>
                      )}
                    </section>
                  )}
                  {page === "knowledge" &&
                    (filtered.length ? (
                      <div className="agent-grid">
                        {filtered.map((c) => (
                          <article className="card collection-card" key={c.id}>
                            <div className="agent-symbol">
                              <BookOpen size={25} />
                            </div>
                            <h2>{c.name}</h2>
                            <p>
                              {c.description ||
                                "Approved reference information for your agents."}
                            </p>
                            <button
                              className="text-button"
                              onClick={() =>
                                void run(async () => {
                                  setSelected(c);
                                  setDocuments(
                                    await api(`/collections/${c.id}/documents`),
                                  );
                                  setModal("documents");
                                })
                              }
                            >
                              Manage documents
                              <ArrowRight size={16} />
                            </button>
                          </article>
                        ))}
                      </div>
                    ) : (
                      <section className="card">
                        <Empty title="Give your agents a source of truth">
                          Create a collection for policies, FAQs, or approved
                          patient instructions.
                        </Empty>
                      </section>
                    ))}
                  {page === "numbers" && (
                    <section className="card">
                      {filtered.length ? (
                        <table>
                          <thead>
                            <tr>
                              <th>Phone number</th>
                              <th>Inbound agent</th>
                              <th>Setup</th>
                            </tr>
                          </thead>
                          <tbody>
                            {filtered.map((n) => (
                              <tr key={n.id}>
                                <td>
                                  <strong>{n.number}</strong>
                                  <small>{n.label}</small>
                                </td>
                                <td>
                                  {
                                    agents.find((a) => a.id === n.agent_id)
                                      ?.name
                                  }
                                </td>
                                <td>
                                  <button
                                    className="text-button"
                                    onClick={() => {
                                      setSelected(n);
                                      setModal("number-help");
                                    }}
                                  >
                                    Webhook instructions
                                    <ArrowRight size={15} />
                                  </button>
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      ) : (
                        <Empty title="A familiar number. A helpful voice.">
                          Assign a Twilio number you own, then route its
                          incoming calls to a published agent.
                        </Empty>
                      )}
                    </section>
                  )}
                  {page === "contacts" && (
                    <section className="card">
                      {filtered.length ? (
                        <div className="table-scroll">
                          <table>
                            <thead>
                              <tr>
                                <th>Contact</th>
                                <th>Phone</th>
                                <th>Calling preference</th>
                                <th>Timezone</th>
                                <th />
                              </tr>
                            </thead>
                            <tbody>
                              {filtered.map((c) => (
                                <tr key={c.id}>
                                  <td>
                                    <strong>{c.name}</strong>
                                  </td>
                                  <td>{c.phone}</td>
                                  <td>
                                    <Badge
                                      value={
                                        c.opted_out
                                          ? "opted_out"
                                          : c.consent
                                            ? "consented"
                                            : "no_consent"
                                      }
                                    />
                                  </td>
                                  <td>{c.timezone}</td>
                                  <td>
                                    {canEdit && (
                                      <button
                                        className="text-button"
                                        onClick={() =>
                                          startModal("contact", {
                                            ...c,
                                            variables: JSON.stringify(
                                              c.variables,
                                              null,
                                              2,
                                            ),
                                          })
                                        }
                                      >
                                        Edit
                                      </button>
                                    )}
                                  </td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      ) : (
                        <Empty title="Thoughtful outreach starts with consent">
                          Add a contact and their calling preferences before
                          scheduling an outbound call.
                        </Empty>
                      )}
                    </section>
                  )}
                  {page === "campaigns" &&
                    (filtered.length ? (
                      <div className="campaign-list">
                        {filtered.map((c) => (
                          <section className="card campaign-card" key={c.id}>
                            <div>
                              <div className="campaign-heading">
                                <h2>{c.name}</h2>
                                <Badge value={c.status} />
                              </div>
                              <p>
                                {c.recipients.length} contacts · Up to{" "}
                                {c.config.max_attempts} attempts ·{" "}
                                {c.config.window_start}:00–{c.config.window_end}
                                :00 local time
                              </p>
                              <div className="progress-track">
                                <div
                                  style={{
                                    width: `${c.recipients.length ? (c.recipients.filter((r: Row) => ["completed", "failed", "suppressed"].includes(r.status)).length / c.recipients.length) * 100 : 0}%`,
                                  }}
                                />
                              </div>
                              <small>
                                {
                                  c.recipients.filter(
                                    (r: Row) => r.status === "completed",
                                  ).length
                                }{" "}
                                completed ·{" "}
                                {
                                  c.recipients.filter(
                                    (r: Row) => r.status === "failed",
                                  ).length
                                }{" "}
                                failed ·{" "}
                                {
                                  c.recipients.filter(
                                    (r: Row) => r.status === "suppressed",
                                  ).length
                                }{" "}
                                suppressed
                              </small>
                            </div>
                            <div className="actions">
                              {canEdit &&
                                !["completed", "cancelled"].includes(
                                  c.status,
                                ) && (
                                  <>
                                    <Button
                                      disabled={busy}
                                      onClick={() =>
                                        void run(async () => {
                                          await api(
                                            `/campaigns/${c.id}/${c.status === "running" ? "pause" : "start"}`,
                                            "POST",
                                          );
                                          refresh();
                                          setNotice("Campaign updated");
                                        })
                                      }
                                    >
                                      {c.status === "running" ? (
                                        <Pause size={15} />
                                      ) : (
                                        <Play size={15} />
                                      )}{" "}
                                      {c.status === "running"
                                        ? "Pause"
                                        : "Start campaign"}
                                    </Button>
                                    <Button
                                      disabled={busy}
                                      onClick={() =>
                                        void run(async () => {
                                          await api(
                                            `/campaigns/${c.id}/cancel`,
                                            "POST",
                                          );
                                          refresh();
                                        })
                                      }
                                    >
                                      Cancel
                                    </Button>
                                  </>
                                )}
                            </div>
                          </section>
                        ))}
                      </div>
                    ) : (
                      <section className="card">
                        <Empty title="Be there before they need to call">
                          Create an appointment reminder or follow-up campaign
                          with local calling windows and bounded retries.
                        </Empty>
                      </section>
                    ))}
                  {page === "calls" && (
                    <section className="card">
                      {filtered.length ? (
                        <CallTable
                          rows={filtered}
                          agents={agents}
                          open={(id) =>
                            void run(async () =>
                              setCall(await api("/calls/" + id)),
                            )
                          }
                        />
                      ) : (
                        <Empty title="A clear record of every conversation">
                          Simulation and telephone calls will appear here with
                          their transcripts, sources, and actions.
                        </Empty>
                      )}
                    </section>
                  )}
                  {page === "tasks" && (
                    <section className="card">
                      {filtered.length ? (
                        filtered.map((t) => (
                          <div className="task-row" key={t.id}>
                            <div className="task-symbol">
                              <ClipboardList size={20} />
                            </div>
                            <div>
                              <h3>{t.title}</h3>
                              <p>{t.details}</p>
                              <small>{date(t.created_at)}</small>
                            </div>
                            <Badge value={t.status} />
                            {t.status === "open" && canEdit && (
                              <Button
                                disabled={busy}
                                onClick={() =>
                                  void run(async () => {
                                    await api(`/tasks/${t.id}/resolve`, "POST");
                                    refresh();
                                  })
                                }
                              >
                                <Check size={15} />
                                Resolve
                              </Button>
                            )}
                          </div>
                        ))
                      ) : (
                        <Empty title="Nothing waiting on your team">
                          Callback requests, scheduling changes, and provider
                          issues will appear here.
                        </Empty>
                      )}
                    </section>
                  )}
                  {page === "settings" && (
                    <div className="settings-grid">
                      <section className="card padded">
                        <h2>Workspace</h2>
                        <p className="muted">
                          Hospital identity and conversation retention.
                        </p>
                        <form
                          onSubmit={formSubmit(async () => {
                            const form =
                              document.querySelector<HTMLFormElement>(
                                "#workspace-form",
                              )!;
                            const fields = new FormData(form);
                            const workspace = await api("/workspace", "PUT", {
                              name: fields.get("name"),
                              timezone: fields.get("timezone"),
                              retention_days: Number(
                                fields.get("retention_days"),
                              ),
                            });
                            setSession({ ...session, workspace });
                            setNotice("Workspace saved");
                          })}
                          id="workspace-form"
                        >
                          <Field label="Name">
                            <input
                              name="name"
                              defaultValue={session.workspace.name}
                              required
                            />
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
                            <Button
                              onClick={() =>
                                startModal("user", { role: "operator" })
                              }
                            >
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
                          Administrators manage credentials and publish agents.
                          Operators manage calls and drafts. Viewers have
                          read-only access.
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
                  )}
                </>
              )}
            </>
          )}
          <footer className="page-footer">
            <span>
              PulseMux <span> / </span> Clinical voice operations
            </span>
            <span>
              <span className="online-dot" />
              Self-hosted · v0.2
            </span>
          </footer>
        </main>
      </div>
      {modal && (
        <Modal
          title={
            (
              {
                templates: "Choose a starting point",
                connection: draft.id
                  ? "Rotate credentials"
                  : "Add a connection",
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
                    embedding_connection_id:
                      draft.embedding_connection_id || null,
                  });
                  saveDone("Collection created");
                }
                if (modal === "document") {
                  await api(`/collections/${selected!.id}/documents`, "POST", {
                    title: draft.title,
                    content: draft.content,
                  });
                  setDocuments(
                    await api(`/collections/${selected!.id}/documents`),
                  );
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
                  saveDone(
                    "Campaign created as draft. Review it before starting.",
                  );
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
                        draft._providers || [
                          "deepgram",
                          "groq",
                          "openai",
                          "twilio",
                        ]
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
                    <Field label="API key">
                      {input("api_key", "password")}
                    </Field>
                  )}
                  <div className="info-panel">
                    <ShieldCheck size={20} />
                    <p>
                      Encrypted before storage. Saved credentials cannot be
                      revealed in the dashboard. Rotating a key replaces it for
                      future requests.
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
                  <Field label="Inbound agent">
                    {select("agent_id", agents)}
                  </Field>
                </>
              )}
              {modal === "contact" && (
                <>
                  <div className="form-grid">
                    <Field label="Name">{input("name")}</Field>
                    <Field
                      label="Phone number"
                      hint="Include + and country code."
                    >
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
                      onChange={(e) =>
                        setDraft({ ...draft, role: e.target.value })
                      }
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
                Additional columns become agent variables. Consent must
                explicitly be true, yes, or 1; missing consent defaults to
                false. Existing phone numbers are skipped.
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
                    {draft.contacts.length} valid contacts ·{" "}
                    {draft.errors.length} invalid rows
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
                        busy ||
                        !draft.contacts.length ||
                        draft.errors.length > 0
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
                                await api(
                                  `/collections/${selected!.id}/documents`,
                                ),
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
                  Add reference text or upload a file. Documents require
                  approval before agents can use them.
                </Empty>
              )}
            </div>
          )}
          {modal === "number-help" && (
            <div className="modal-content">
              <p>
                In the Twilio Console, open <strong>{selected?.number}</strong>.
                Under Voice configuration, set “A call comes in” to Webhook
                (HTTP POST):
              </p>
              <pre>
                {location.origin}/api/twilio/{selected?.connection_id}/inbound
              </pre>
              <p className="muted">
                Use your deployment’s public HTTPS origin. Set the same origin
                as PUBLIC_BASE_URL on the server. Incoming requests and media
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
                <li>
                  Add your speech, language model, and Twilio connections.
                </li>
                <li>Create an agent from a workflow template.</li>
                <li>
                  Attach approved knowledge, then save and test the draft.
                </li>
                <li>Publish the tested agent and assign a number.</li>
                <li>Place a call or create an outreach campaign.</li>
              </ol>
              <p>
                Real telephone calls need a public HTTPS origin, an owned Twilio
                number, and a running campaign worker. Appointment changes
                currently create staff requests.
              </p>
              <p className="muted">
                Deployments handling patient information need reviewed operating
                procedures and provider agreements. No call audio is recorded by
                this platform.
              </p>
            </div>
          )}
        </Modal>
      )}
      {call && (
        <Modal
          title="Conversation details"
          subtitle={`${call.direction} · ${date(call.created_at)}`}
          wide
          onClose={() => setCall(null)}
        >
          <div className="modal-content">
            <div className="call-summary">
              <Badge value={call.status} />
              <span>
                {call.outcome?.replaceAll("_", " ") || "No outcome recorded"}
              </span>
              <span>{call.to_number || "Browser simulator"}</span>
            </div>
            {call.error && <div className="alert error">{call.error}</div>}
            <div className="transcript">
              {call.events.map((e: Row) =>
                e.kind === "transcript" ? (
                  <div
                    key={e.id}
                    className={
                      "transcript-message " +
                      (e.payload.speaker === "PATIENT" ? "patient" : "")
                    }
                  >
                    <small>
                      {e.payload.speaker === "PATIENT" ? "Caller" : "Assistant"}{" "}
                      · {date(e.created_at)}
                    </small>
                    <p>{e.payload.text}</p>
                  </div>
                ) : e.kind === "tool" ? (
                  <div className="transcript-event" key={e.id}>
                    <Zap size={14} />
                    {e.payload.action?.replaceAll("_", " ")} ·{" "}
                    {e.payload.outcome}
                  </div>
                ) : e.kind === "knowledge_sources" &&
                  e.payload.sources?.length ? (
                  <div className="transcript-event" key={e.id}>
                    <BookOpen size={14} />
                    Sources:{" "}
                    {e.payload.sources.map((s: Row) => s.title).join(", ")}
                  </div>
                ) : ["error", "tts_warning"].includes(e.kind) ? (
                  <div className="transcript-event" key={e.id}>
                    {e.payload.message}
                  </div>
                ) : null,
              )}
              {!call.events.some((e: Row) => e.kind === "transcript") && (
                <Empty title="No transcript yet">
                  Conversation events will appear here after the call starts.
                </Empty>
              )}
            </div>
          </div>
        </Modal>
      )}
    </div>
  );
}
function CallTable({
  rows,
  agents,
  open,
}: {
  rows: Row[];
  agents: Row[];
  open: (id: string) => void;
}) {
  return (
    <div className="table-scroll">
      <table>
        <thead>
          <tr>
            <th>Agent / contact</th>
            <th>Channel</th>
            <th>Status</th>
            <th>Started</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {rows.map((c) => (
            <tr key={c.id}>
              <td>
                <strong>
                  {agents.find((a) => a.id === c.agent_id)?.name || "Agent"}
                </strong>
                <small>
                  {c.to_number || c.from_number || "Browser conversation"}
                </small>
              </td>
              <td>
                <span className="channel">
                  {c.direction === "inbound" ? (
                    <ArrowDownLeft size={15} />
                  ) : c.direction === "outbound" ? (
                    <ArrowUpRight size={15} />
                  ) : (
                    <AudioLines size={15} />
                  )}{" "}
                  {c.direction}
                </span>
              </td>
              <td>
                <Badge value={c.status} />
              </td>
              <td>{date(c.created_at)}</td>
              <td>
                <button
                  className="icon-button"
                  aria-label="View call details"
                  onClick={() => open(c.id)}
                >
                  <ArrowRight size={17} />
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

const rootElement = document.getElementById("root");
if (rootElement)
  createRoot(rootElement).render(
    <React.StrictMode>
      <App />
    </React.StrictMode>,
  );
