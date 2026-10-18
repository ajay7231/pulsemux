import { FormEvent, useEffect, useState } from "react";
import { AgentEditor } from "./features/agents/AgentEditor";
import { AuthPage } from "./features/auth/AuthPage";
import { CallDetailsDialog } from "./features/calls/CallDetailsDialog";
import { WorkspaceDialog } from "./features/workspace/WorkspaceDialog";
import { WorkspacePage } from "./features/workspace/WorkspacePage";
import { agentFingerprint, editableAgent } from "./lib/agents";
import { api } from "./lib/api";
import { DEFAULT_CONFIG, LABELS, NAV, VOICES } from "./lib/config";
import type { Page, Row } from "./lib/types";

import {
  Activity,
  CheckCircle2,
  CircleHelp,
  LogOut,
  ShieldCheck,
  X,
} from "lucide-react";

import { AgentTest } from "./features/agents/AgentTest";

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
      <AuthPage
        loading={loading}
        setup={setup}
        error={error}
        formSubmit={formSubmit}
        draft={draft}
        setSession={setSession}
        setDraft={setDraft}
        setSetup={setSetup}
        setupTokenRequired={setupTokenRequired}
        input={input}
        timezones={timezones}
        busy={busy}
        setupAvailable={setupAvailable}
      />
    );
  const config = editor?.config || {};
  const unsaved =
    !!editor?.id && editor._savedFingerprint !== agentFingerprint(editor);
  function cf(key: string, value: any) {
    setEditor((prev) =>
      prev ? { ...prev, config: { ...prev.config, [key]: value } } : prev,
    );
  }
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
                  setEditor(editableAgent(updated));
                  refresh();
                });
              }}
            />
          ) : editor ? (
            <AgentEditor
              startModal={startModal}
              setEditor={setEditor}
              editor={editor}
              busy={busy}
              canEdit={canEdit}
              run={run}
              refresh={refresh}
              setNotice={setNotice}
              unsaved={unsaved}
              config={config}
              setAgentTab={setAgentTab}
              setError={setError}
              setSimulator={setSimulator}
              isAdmin={isAdmin}
              agentTab={agentTab}
              templates={templates}
              cf={cf}
              connections={connections}
              collections={collections}
            />
          ) : (
            <WorkspacePage
              page={page}
              session={session}
              canEdit={canEdit}
              busy={busy}
              isAdmin={isAdmin}
              startModal={startModal}
              loading={loading}
              navigate={navigate}
              overview={overview}
              agents={agents}
              run={run}
              setCall={setCall}
              connections={connections}
              collections={collections}
              numbers={numbers}
              search={search}
              setSearch={setSearch}
              filtered={filtered}
              refresh={refresh}
              templates={templates}
              setEditor={setEditor}
              setAgentTab={setAgentTab}
              setNotice={setNotice}
              setSelected={setSelected}
              setDocuments={setDocuments}
              setModal={setModal}
              formSubmit={formSubmit}
              setSession={setSession}
              timezones={timezones}
              data={data}
            />
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
        <WorkspaceDialog
          draft={draft}
          selected={selected}
          modal={modal}
          setModal={setModal}
          error={error}
          templates={templates}
          newAgent={newAgent}
          formSubmit={formSubmit}
          cf={cf}
          setConnections={setConnections}
          setDraft={setDraft}
          saveDone={saveDone}
          setDocuments={setDocuments}
          setNotice={setNotice}
          session={session}
          navigate={navigate}
          input={input}
          connections={connections}
          select={select}
          agents={agents}
          timezones={timezones}
          numbers={numbers}
          contacts={contacts}
          busy={busy}
          run={run}
          canEdit={canEdit}
          documents={documents}
          isAdmin={isAdmin}
          refresh={refresh}
        />
      )}
      {call && <CallDetailsDialog call={call} setCall={setCall} />}
    </div>
  );
}
