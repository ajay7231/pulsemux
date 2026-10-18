import { RefreshCw, Phone, Plus, Search, Upload } from "lucide-react";
import { lazy, Suspense } from "react";
import { Button, Skeleton } from "../../components/ui";
import { LABELS } from "../../lib/config";
import { Page, Row } from "../../lib/types";
import type { WorkspacePageProps } from "./types";
const AgentsPage = lazy(() =>
  import("./AgentsPage").then((m) => ({ default: m.AgentsPage })),
);
const CallsPage = lazy(() =>
  import("./CallsPage").then((m) => ({ default: m.CallsPage })),
);
const CampaignsPage = lazy(() =>
  import("./CampaignsPage").then((m) => ({ default: m.CampaignsPage })),
);
const ConnectionsPage = lazy(() =>
  import("./ConnectionsPage").then((m) => ({ default: m.ConnectionsPage })),
);
const ContactsPage = lazy(() =>
  import("./ContactsPage").then((m) => ({ default: m.ContactsPage })),
);
const KnowledgePage = lazy(() =>
  import("./KnowledgePage").then((m) => ({ default: m.KnowledgePage })),
);
const NumbersPage = lazy(() =>
  import("./NumbersPage").then((m) => ({ default: m.NumbersPage })),
);
const OverviewPage = lazy(() =>
  import("./OverviewPage").then((m) => ({ default: m.OverviewPage })),
);
const SettingsPage = lazy(() =>
  import("./SettingsPage").then((m) => ({ default: m.SettingsPage })),
);
const TasksPage = lazy(() =>
  import("./TasksPage").then((m) => ({ default: m.TasksPage })),
);

export function WorkspacePage({
  page,
  session,
  canEdit,
  busy,
  isAdmin,
  startModal,
  loading,
  navigate,
  overview,
  agents,
  run,
  setCall,
  connections,
  collections,
  numbers,
  search,
  setSearch,
  filtered,
  refresh,
  templates,
  setEditor,
  setAgentTab,
  setNotice,
  setSelected,
  setDocuments,
  setModal,
  formSubmit,
  setSession,
  timezones,
  data,
  pagination,
  sort,
  setSort,
}: WorkspacePageProps) {
  return (
    <>
      <div className="page-heading">
        <div>
          <h1>
            {page === "overview"
              ? `Welcome back, ${session.user.name.split(" ")[0]}.`
              : LABELS[page]}
          </h1>
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
                  (["connections", "numbers"].includes(page) && !isAdmin)
                }
                onClick={() => {
                  if (page === "agents") startModal("templates");
                  else if (page === "knowledge") startModal("collection");
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
            <Button kind="primary" onClick={() => startModal("outbound")}>
              <Phone size={16} />
              Place a call
            </Button>
          )}
        </div>
      </div>
      <Suspense fallback={<Skeleton label="Loading page" />}>
        {loading ? (
          <Skeleton label="Loading workspace" />
        ) : page === "overview" ? (
          <OverviewPage
            navigate={navigate}
            overview={overview}
            agents={agents}
            run={run}
            setCall={setCall}
            connections={connections}
            collections={collections}
            numbers={numbers}
          />
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
                  {pagination.total}{" "}
                  {page === "knowledge"
                    ? "collections"
                    : LABELS[page].toLowerCase()}
                </span>
                <select
                  aria-label="Sort records"
                  value={sort}
                  onChange={(event) => setSort(event.target.value)}
                >
                  <option value="newest">Newest first</option>
                  <option value="oldest">Oldest first</option>
                </select>
                <button
                  className="icon-button"
                  aria-label="Refresh records"
                  onClick={refresh}
                >
                  <RefreshCw size={17} />
                </button>
              </div>
            )}
            {page === "agents" && (
              <AgentsPage
                startModal={startModal}
                filtered={filtered}
                templates={templates}
                setEditor={setEditor}
                setAgentTab={setAgentTab}
              />
            )}
            {page === "connections" && (
              <ConnectionsPage
                busy={busy}
                isAdmin={isAdmin}
                startModal={startModal}
                run={run}
                filtered={filtered}
                refresh={refresh}
                setNotice={setNotice}
              />
            )}
            {page === "knowledge" && (
              <KnowledgePage
                run={run}
                filtered={filtered}
                setSelected={setSelected}
                setDocuments={setDocuments}
                setModal={setModal}
              />
            )}
            {page === "numbers" && (
              <NumbersPage
                agents={agents}
                filtered={filtered}
                setSelected={setSelected}
                setModal={setModal}
              />
            )}
            {page === "contacts" && (
              <ContactsPage
                canEdit={canEdit}
                startModal={startModal}
                filtered={filtered}
              />
            )}
            {page === "campaigns" && (
              <CampaignsPage
                canEdit={canEdit}
                busy={busy}
                run={run}
                filtered={filtered}
                refresh={refresh}
                setNotice={setNotice}
              />
            )}
            {page === "calls" && (
              <CallsPage
                agents={agents}
                run={run}
                setCall={setCall}
                filtered={filtered}
              />
            )}
            {page === "tasks" && (
              <TasksPage
                canEdit={canEdit}
                busy={busy}
                run={run}
                filtered={filtered}
                refresh={refresh}
              />
            )}
            {page === "settings" && (
              <SettingsPage
                session={session}
                busy={busy}
                isAdmin={isAdmin}
                startModal={startModal}
                run={run}
                setNotice={setNotice}
                setDocuments={setDocuments}
                setModal={setModal}
                formSubmit={formSubmit}
                setSession={setSession}
                timezones={timezones}
                data={data}
              />
            )}
          </>
        )}
      </Suspense>
      {page !== "overview" && pagination.total > 0 && (
        <nav className="pagination" aria-label="Record pages">
          <Button
            disabled={pagination.page <= 1 || loading}
            onClick={() => pagination.setPage(pagination.page - 1)}
          >
            Previous
          </Button>
          <span>
            Page {pagination.page} of {pagination.pages} · {pagination.total}{" "}
            records
          </span>
          <Button
            disabled={pagination.page >= pagination.pages || loading}
            onClick={() => pagination.setPage(pagination.page + 1)}
          >
            Next
          </Button>
        </nav>
      )}
    </>
  );
}
