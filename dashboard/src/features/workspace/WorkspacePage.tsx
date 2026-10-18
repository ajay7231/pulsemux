import { Activity, Phone, Plus, Search, Upload } from "lucide-react";
import { Button } from "../../components/ui";
import { LABELS } from "../../lib/config";
import { Page, Row } from "../../lib/types";
import { AgentsPage } from "./AgentsPage";
import { CallsPage } from "./CallsPage";
import { CampaignsPage } from "./CampaignsPage";
import { ConnectionsPage } from "./ConnectionsPage";
import { ContactsPage } from "./ContactsPage";
import { KnowledgePage } from "./KnowledgePage";
import { NumbersPage } from "./NumbersPage";
import { OverviewPage } from "./OverviewPage";
import { SettingsPage } from "./SettingsPage";
import { TasksPage } from "./TasksPage";
import type { WorkspacePageProps } from "./types";

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
}: WorkspacePageProps) {
  return (
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
    </>
  );
}
