import {
  Activity,
  CalendarClock,
  CheckCircle2,
  ArrowRight,
  AudioLines,
  Bot,
  Check,
  ClipboardList,
  Megaphone,
} from "lucide-react";
import { Button, Empty } from "../../components/ui";
import { Page } from "../../lib/types";
import { operationService } from "../../services/platform";
import { CallTable } from "../calls/CallTable";
import type { WorkspacePageProps } from "./types";
type Props = Pick<
  WorkspacePageProps,
  | "navigate"
  | "overview"
  | "agents"
  | "run"
  | "setCall"
  | "connections"
  | "collections"
  | "numbers"
>;
export function OverviewPage({
  navigate,
  overview,
  agents,
  run,
  setCall,
}: Props) {
  return (
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
            "Open staff tasks",
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
            </div>
            <button className="text-button" onClick={() => navigate("calls")}>
              View all
              <ArrowRight size={14} />
            </button>
          </div>
          {overview.recent_calls?.length ? (
            <CallTable
              rows={overview.recent_calls}
              agents={agents}
              open={(id) =>
                void run(async () => setCall(await operationService.call(id)))
              }
            />
          ) : (
            <Empty title="Your first conversation starts here">
              Create an agent, connect a provider, and test it in the simulator.
              <Button onClick={() => navigate("agents")}>
                Set up an agent
                <ArrowRight size={15} />
              </Button>
            </Empty>
          )}
        </section>
        <section className="card getting-started">
          <h2>Workspace setup</h2>
          {[
            [overview.connections > 0, "Connect your providers", "connections"],
            [overview.agents > 0, "Create your first agent", "agents"],
            [overview.collections > 0, "Add hospital knowledge", "knowledge"],
            [overview.numbers > 0, "Connect a phone number", "numbers"],
          ].map(([done, label, target], i) => (
            <button key={i} onClick={() => navigate(target as Page)}>
              <span className={done ? "step-done" : "step-circle"}>
                {done ? <Check size={14} /> : i + 1}
              </span>
              <span>{label as string}</span>
              <ArrowRight size={14} />
            </button>
          ))}
        </section>
      </div>
    </>
  );
}
