import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  FormEvent,
  lazy,
  Suspense,
  useEffect,
  useRef,
  useState,
  type Dispatch,
  type SetStateAction,
} from "react";
import {
  Link,
  Outlet,
  useBlocker,
  useLocation,
  useNavigate,
  useSearchParams,
} from "react-router-dom";
import { useSession } from "./app/SessionProvider";
import { useDashboardRoute } from "./app/router";
import {
  resourceForPage,
  useOptions,
  useWorkspaceList,
  useWorkspaceOverview,
  workspaceKey,
} from "./app/useWorkspaceQueries";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { Button, Modal } from "./components/ui";
import type { AgentConfig } from "./contracts/schemas";
import { ApiError } from "./lib/api";
import { agentService, metadataService } from "./services/platform";
const AgentEditor = lazy(() =>
  import("./features/agents/AgentEditor").then((m) => ({
    default: m.AgentEditor,
  })),
);

import { CallDetailsDialog } from "./features/calls/CallDetailsDialog";
import { WorkspacePage } from "./features/workspace/WorkspacePage";
import { agentFingerprint, editableAgent } from "./lib/agents";
import { api } from "./lib/api";
import { DEFAULT_CONFIG, LABELS, NAV, VOICES } from "./lib/config";
import type { Page, Row } from "./lib/types";
const WorkspaceDialog = lazy(() =>
  import("./features/workspace/WorkspaceDialog").then((m) => ({
    default: m.WorkspaceDialog,
  })),
);

import {
  Activity,
  CheckCircle2,
  CircleHelp,
  LogOut,
  ShieldCheck,
  X,
} from "lucide-react";

const AgentTest = lazy(() =>
  import("./features/agents/AgentTest").then((m) => ({ default: m.AgentTest })),
);

export function App() {
  const auth = useSession();
  const session = auth.session!;
  const setSession = auth.setSession;
  const location = useLocation();
  const route = useDashboardRoute();
  const page = route.page || "overview";
  const routerNavigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const queryClient = useQueryClient();
  const committedNavigation = useRef(false);
  const [busyCount, setBusyCount] = useState(0);
  const busy = busyCount > 0;
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [modal, updateModal] = useState("");
  const [selected, setSelected] = useState<Row | null>(null);
  const [editor, updateEditor] = useState<Row | null>(null);
  const [agentTab, setAgentTab] = useState("Identity");
  const [documents, setDocuments] = useState<Row[]>([]);
  const [dialogInitial, setDialogInitial] = useState<Row>({});
  const [simulator, updateSimulator] = useState<Row | null>(null);
  const [call, setCall] = useState<Row | null>(null);
  const setModal: Dispatch<SetStateAction<string>> = (value) => {
    updateModal(value);
    if (value === "") setDialogInitial({});
  };
  const search = params.get("q") || "";
  const listPage = Math.min(
    1000000,
    Math.max(1, Math.floor(Number(params.get("page"))) || 1),
  );
  const sort = params.get("sort") || "newest";
  const updateParams = (values: Record<string, string>) =>
    setParams(
      (previous) => {
        const next = new URLSearchParams(previous);
        Object.entries(values).forEach(([key, value]) => next.set(key, value));
        return next;
      },
      { replace: true },
    );
  const setSearch = (value: string | ((value: string) => string)) =>
    updateParams({
      q: typeof value === "function" ? value(search) : value,
      page: "1",
    });
  const setSort = (value: string) => updateParams({ sort: value, page: "1" });
  const forbidden =
    route.role === "admin"
      ? session.user.role !== "admin"
      : route.role === "operator" && session.user.role === "viewer";
  const setEditor: Dispatch<SetStateAction<Row | null>> = (value) => {
    if (typeof value === "function") {
      updateEditor(value);
      return;
    }
    if (!value) {
      routerNavigate("/dashboard/agents");
      return;
    }
    updateEditor(value);
    const destination = value.id
      ? `/dashboard/agents/${value.id}`
      : "/dashboard/agents/new";
    if (location.pathname !== destination) {
      committedNavigation.current =
        value._savedFingerprint === agentFingerprint(value);
      routerNavigate(destination);
      queueMicrotask(() => {
        committedNavigation.current = false;
      });
    }
  };
  const setSimulator: Dispatch<SetStateAction<Row | null>> = (value) => {
    if (typeof value === "function") {
      updateSimulator(value);
      return;
    }
    if (value) {
      updateSimulator(value);
      routerNavigate(`/dashboard/agents/${value.id}/simulate`);
    } else {
      updateSimulator(null);
      if (route.agentId) routerNavigate(`/dashboard/agents/${route.agentId}`);
    }
  };
  const canEdit = session?.user.role !== "viewer",
    isAdmin = session?.user.role === "admin";
  const refresh = () => {
    const resource = resourceForPage[page];
    void queryClient.invalidateQueries({
      predicate: (query) =>
        query.queryKey[0] === "workspace" &&
        query.queryKey[1] === session.workspace.id &&
        (query.queryKey[2] === "overview" ||
          query.queryKey[3] === resource ||
          query.queryKey[3] === route.agentId),
    });
  };
  const run = async (fn: () => Promise<void>) => {
    setBusyCount((value) => value + 1);
    setError("");
    setNotice("");
    try {
      await fn();
    } catch (cause) {
      if (!(cause instanceof ApiError && cause.status === 401))
        setError(
          cause instanceof Error
            ? cause.message
            : "The operation could not be completed.",
        );
    } finally {
      setBusyCount((value) => Math.max(0, value - 1));
    }
  };
  const list = useWorkspaceList(
    session.workspace.id,
    page,
    {
      page: listPage,
      pageSize: 25,
      search,
      sort: "created_at",
      direction: sort === "oldest" ? "asc" : "desc",
    },
    isAdmin,
  );
  useEffect(() => {
    if (list.data && listPage > Math.max(1, list.data.pages))
      updateParams({ page: String(Math.max(1, list.data.pages)) });
  }, [list.data?.pages, listPage]);
  const overviewQuery = useWorkspaceOverview(
    session.workspace.id,
    page === "overview",
  );
  const editingAgent = !!editor || !!route.agentId || route.mode === "new";
  const c = useOptions(
    session.workspace.id,
    "connections",
    editingAgent || ["number", "collection"].includes(modal),
  );
  const k = useOptions(session.workspace.id, "collections", editingAgent);
  const a = useOptions(
    session.workspace.id,
    "agents",
    ["number", "outbound", "campaign"].includes(modal),
  );
  const n = useOptions(
    session.workspace.id,
    "numbers",
    ["outbound", "campaign"].includes(modal),
  );
  const templatesQuery = useQuery({
    queryKey: [...workspaceKey(session.workspace.id), "templates"],
    queryFn: ({ signal }) => metadataService.templates(signal),
    staleTime: Infinity,
  });
  const timezoneQuery = useQuery({
    queryKey: ["timezones"],
    queryFn: ({ signal }) =>
      api<string[]>("/timezones", "GET", undefined, { signal }),
    staleTime: Infinity,
  });
  const connections: Row[] = c.data || [],
    collections: Row[] = k.data || [],
    agents: Row[] = a.data || overviewQuery.data?.agent_choices || [],
    numbers: Row[] = n.data || [],
    templates = templatesQuery.data || [],
    timezones = timezoneQuery.data || ["Asia/Kolkata", "UTC"];
  const setConnections: Dispatch<SetStateAction<Row[]>> = (value) =>
    queryClient.setQueryData(
      [...workspaceKey(session.workspace.id), "options", "connections"],
      (previous: Row[] = []) =>
        typeof value === "function" ? value(previous) : value,
    );
  const data: Row[] = list.data?.items || [],
    filtered = data;
  const overview: Row = overviewQuery.data || {};
  const loading =
    page === "overview"
      ? overviewQuery.isPending
      : page === "settings" && !isAdmin
        ? false
        : list.isPending;
  const dataError =
    list.error ||
    overviewQuery.error ||
    c.error ||
    k.error ||
    a.error ||
    n.error ||
    templatesQuery.error;
  const selectedAgent = useQuery({
    queryKey: [...workspaceKey(session.workspace.id), "agent", route.agentId],
    enabled: !!route.agentId && !forbidden,
    queryFn: ({ signal }) => agentService.get(route.agentId!, signal),
  });
  useEffect(() => {
    setError("");
    updateModal("");
    setDialogInitial({});
    setSelected(null);
    setCall(null);
    setSearchInputResetKey(location.pathname);
    if (!route.agentId && route.mode !== "new") {
      updateEditor(null);
      updateSimulator(null);
    }
    if (route.mode !== "simulate") updateSimulator(null);
    if (
      location.pathname === "/dashboard" ||
      location.pathname === "/dashboard/"
    )
      routerNavigate("/dashboard/overview", { replace: true });
  }, [location.pathname]);
  useEffect(() => {
    if (route.agentId && selectedAgent.data && !forbidden) {
      if (editor?.id !== route.agentId)
        updateEditor(editableAgent(selectedAgent.data));
      if (route.mode === "simulate")
        updateSimulator((previous) =>
          previous?.id === route.agentId ? previous : selectedAgent.data!,
        );
    }
  }, [route.agentId, route.mode, selectedAgent.data, forbidden]);
  useEffect(() => {
    if (route.mode === "new" && (!editor || editor.id)) newAgent();
  }, [route.mode, location.pathname]);
  const [searchInputResetKey, setSearchInputResetKey] = useState(
    location.pathname,
  );
  useEffect(() => {
    if (!notice) return;
    const timer = setTimeout(() => setNotice(""), 7000);
    return () => clearTimeout(timer);
  }, [notice]);
  function navigate(next: Page) {
    routerNavigate(`/dashboard/${next}`);
  }
  function newAgent(template?: Row) {
    const next = {
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
    };
    setEditor(editableAgent(next));
    setAgentTab("Identity");
    setModal("");
  }
  function startModal(name: string, initial: Row = {}) {
    setDialogInitial(initial);
    setModal(name);
    setError("");
  }
  const formSubmit = (fn: () => Promise<void>) => (event: FormEvent) => {
    event.preventDefault();
    void run(fn);
  };
  const saveDone = (message: string) => {
    setModal("");
    refresh();
    setNotice(message);
  };
  const config = editor?.config || {};
  const unsaved =
    !!editor && editor._savedFingerprint !== agentFingerprint(editor);
  function cf<K extends keyof AgentConfig>(key: K, value: AgentConfig[K]) {
    setEditor((prev) =>
      prev ? { ...prev, config: { ...prev.config, [key]: value } } : prev,
    );
  }
  const blocker = useBlocker(
    ({ currentLocation, nextLocation }) =>
      !committedNavigation.current &&
      unsaved &&
      currentLocation.pathname !== nextLocation.pathname,
  );
  useEffect(() => {
    const prevent = (event: BeforeUnloadEvent) => {
      if (unsaved) {
        event.preventDefault();
        event.returnValue = "";
      }
    };
    window.addEventListener("beforeunload", prevent);
    return () => window.removeEventListener("beforeunload", prevent);
  }, [unsaved]);
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
              aria-current={page === key ? "page" : undefined}
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
            onClick={() => {
              updateEditor(null);
              void auth.logout();
            }}
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
      <a className="skip-link" href="#workspace-content">
        Skip to workspace content
      </a>
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
        <main key={searchInputResetKey} id="workspace-content" tabIndex={-1}>
          <Suspense
            fallback={
              <div className="loading" role="status">
                Loading page…
              </div>
            }
          >
            <ErrorBoundary resetKey={location.pathname}>
              {dataError && (
                <div className="alert error" role="alert">
                  {dataError.message}
                  <button className="button" onClick={refresh}>
                    Retry
                  </button>
                </div>
              )}
              {error && (
                <div className="alert error" role="alert">
                  {error}
                  <button
                    aria-label="Dismiss error"
                    onClick={() => setError("")}
                  >
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
              {forbidden ? (
                <section className="card padded" role="alert">
                  <h1>Access restricted</h1>
                  <p>
                    You do not have permission to use this feature. Ask an
                    administrator for access.
                  </p>
                  <Link className="button" to="/dashboard/overview">
                    Back to overview
                  </Link>
                </section>
              ) : route.notFound ? (
                <Outlet />
              ) : selectedAgent.isError ? (
                <section className="card padded" role="alert">
                  <h1>
                    {selectedAgent.error instanceof ApiError &&
                    selectedAgent.error.status === 404
                      ? "Agent not found"
                      : "Agent unavailable"}
                  </h1>
                  <p>{selectedAgent.error.message}</p>
                  <button
                    className="button"
                    onClick={() => void selectedAgent.refetch()}
                  >
                    Retry
                  </button>
                  <Link className="button" to="/dashboard/agents">
                    All agents
                  </Link>
                </section>
              ) : route.agentId && selectedAgent.isPending ? (
                <div className="loading" role="status">
                  Loading agent…
                </div>
              ) : simulator ? (
                <AgentTest
                  agent={simulator as any}
                  voice={
                    VOICES[simulator.config.voice_id] ||
                    simulator.config.voice_id
                  }
                  onClose={() => {
                    const id = simulator.id;
                    setSimulator(null);
                    void run(async () => {
                      const updated = await agentService.get(id);
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
                  pagination={{
                    page: listPage,
                    pages: list.data?.pages || 0,
                    total: list.data?.total || 0,
                    pageSize: 25,
                    setPage: (value) => updateParams({ page: String(value) }),
                  }}
                  sort={sort}
                  setSort={setSort}
                />
              )}
            </ErrorBoundary>
          </Suspense>
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
      <Suspense
        fallback={
          <div className="overlay">
            <div className="card padded" role="status">
              Loading dialog…
            </div>
          </div>
        }
      >
        {modal && (
          <WorkspaceDialog
            initial={dialogInitial}
            selected={selected}
            modal={modal}
            setModal={setModal}
            error={error}
            templates={templates}
            newAgent={newAgent}
            formSubmit={formSubmit}
            cf={cf}
            setConnections={setConnections}
            saveDone={saveDone}
            setDocuments={setDocuments}
            setNotice={setNotice}
            session={session}
            navigate={navigate}
            connections={connections}
            agents={agents}
            timezones={timezones}
            numbers={numbers}
            busy={busy}
            run={run}
            canEdit={canEdit}
            documents={documents}
            isAdmin={isAdmin}
            refresh={refresh}
          />
        )}
        {call && <CallDetailsDialog call={call} setCall={setCall} />}
      </Suspense>
      {blocker.state === "blocked" && (
        <Modal
          title="Leave without saving?"
          subtitle="Your agent has unsaved changes."
          onClose={() => blocker.reset()}
        >
          <div className="modal-content">
            <Button onClick={() => blocker.reset()}>Keep editing</Button>
            <Button onClick={() => blocker.proceed()}>
              Discard changes and leave
            </Button>
          </div>
        </Modal>
      )}
    </div>
  );
}
