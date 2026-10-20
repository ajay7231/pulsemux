import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { transferableAbortController } from "node:util";
import { QueryClientProvider } from "@tanstack/react-query";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { SessionProvider } from "./app/SessionProvider";
import { queryClient } from "./app/queryClient";
import { router } from "./app/router";
const routers: ReturnType<typeof createMemoryRouter>[] = [];
beforeEach(() => {
  // React Router uses Node's Request; its signal must come from the same realm.
  vi.stubGlobal(
    "AbortController",
    class {
      constructor() {
        return transferableAbortController();
      }
    },
  );
  Object.defineProperty(HTMLDialogElement.prototype, "showModal", {
    configurable: true,
    value() {
      this.setAttribute("open", "");
    },
  });
  Object.defineProperty(HTMLDialogElement.prototype, "close", {
    configurable: true,
    value() {
      this.removeAttribute("open");
    },
  });
});
function renderApp() {
  const instance = createMemoryRouter(router.routes, {
    initialEntries: ["/dashboard/overview"],
  });
  routers.push(instance);
  return render(
    <QueryClientProvider client={queryClient}>
      <SessionProvider>
        <RouterProvider router={instance} />
      </SessionProvider>
    </QueryClientProvider>,
  );
}
const user = {
  id: "user",
  workspace_id: "hospital",
  created_at: 1,
  email: "ada@example.test",
  active: true,
  name: "Ada Admin",
  role: "admin",
};
const workspace = {
  id: "hospital",
  created_at: 1,
  name: "River Hospital",
  timezone: "Asia/Kolkata",
  retention_days: 90,
};
function mockApi(setup = false, signedIn = true) {
  const requests: { path: string; method: string; body: any }[] = [];
  const savedConnections: any[] = [];
  const savedAgents: any[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: string, init?: RequestInit) => {
      const path = input.replace("/api", "");
      let body: any = null;
      try {
        body = init?.body ? JSON.parse(String(init.body)) : null;
      } catch {}
      requests.push({ path, method: init?.method || "GET", body });
      const responses: Record<string, any> = {
        "/bootstrap": { setup_required: setup, setup_token_required: false },
        "/me": { user, workspace },
        "/setup": { user, workspace },
        "/login": { user, workspace },
        "/timezones": [
          "America/New_York",
          "Asia/Kolkata",
          "Europe/London",
          "UTC",
        ],
        "/connections": savedConnections,
        "/collections": [],
        "/agents": [],
        "/numbers": [],
        "/contacts": [],
        "/templates": [
          {
            id: "reception",
            name: "Inbound reception",
            description: "Answer hospital questions",
            greeting: "Hello, how can I help?",
            instructions:
              "Use approved hospital knowledge. Ask one question at a time.",
          },
        ],
        "/overview": {
          agents: 0,
          calls: 0,
          campaigns: 0,
          contacts: 0,
          active_calls: 0,
          connections: 0,
          collections: 0,
          numbers: 0,
          agent_choices: [],
          recent_activity: [],
          open_tasks: 0,
          recent_calls: [],
        },
      };
      if (path.startsWith("/resources/")) {
        const resource = path.split("/")[2].split("?")[0];
        const items =
          resource === "connections"
            ? savedConnections
            : resource === "agents"
              ? savedAgents
              : [];
        return new Response(
          JSON.stringify({
            items,
            total: items.length,
            page: 1,
            page_size: 25,
            pages: 1,
          }),
        );
      }
      if (path.startsWith("/agents/") && init?.method !== "POST")
        return new Response(
          JSON.stringify(
            savedAgents.find((item) => path === `/agents/${item.id}`),
          ),
        );
      if (path === "/connections" && init?.method === "POST") {
        const connection = {
          id: "new-connection",
          name: body.name,
          provider: body.provider,
          active: true,
          revision: 1,
          test_status: "untested",
          workspace_id: "hospital",
          created_at: 1,
          tested_at: null,
        };
        savedConnections.push(connection);
        return new Response(JSON.stringify(connection));
      }
      if (path === "/me" && !signedIn)
        return new Response(JSON.stringify({ detail: "Sign in required" }), {
          status: 401,
        });
      if (path === "/agents" && init?.method === "POST") {
        const saved = {
          id: "new-agent",
          workspace_id: "hospital",
          created_at: 1,
          updated_at: 1,
          published_version_id: null,
          tested_revision: null,
          tested_knowledge_hash: null,
          ...body,
          status: "draft",
          revision: 1,
        };
        savedAgents.push(saved);
        return new Response(JSON.stringify(saved), { status: 200 });
      }
      return new Response(JSON.stringify(responses[path] ?? []), {
        status: 200,
      });
    }),
  );
  return requests;
}
afterEach(() => {
  cleanup();
  routers.splice(0).forEach((item) => item.dispose());
  queryClient.clear();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  window.history.replaceState(null, "", "/");
});
test("first-run setup creates a workspace without seeded credentials", async () => {
  const requests = mockApi(true);
  const person = userEvent.setup();
  renderApp();
  await screen.findByText("Create your workspace");
  await person.type(
    screen.getByLabelText("Hospital / workspace name"),
    "River Hospital",
  );
  await person.type(screen.getByLabelText("Your name"), "Ada Admin");
  await person.selectOptions(
    screen.getByRole("combobox", { name: "Timezone" }),
    "America/New_York",
  );
  await person.type(screen.getByLabelText("Work email"), "ada@example.test");
  await person.type(screen.getByLabelText("Password"), "long-test-password");
  await person.click(screen.getByRole("button", { name: /Create workspace/ }));
  await screen.findByText("Welcome back, Ada.");
  expect(requests.find((r) => r.path === "/setup")?.body.workspace).toBe(
    "River Hospital",
  );
  expect(requests.find((r) => r.path === "/setup")?.body.timezone).toBe(
    "America/New_York",
  );
  expect(
    await screen.findByText("Your first conversation starts here"),
  ).toBeTruthy();
});
test("template flow saves provider configuration as a real draft", async () => {
  const requests = mockApi();
  const person = userEvent.setup();
  renderApp();
  await screen.findByText("Welcome back, Ada.");
  await person.click(screen.getByRole("button", { name: "Agents" }));
  await screen.findByText("No agents to display");
  await person.click(screen.getByRole("button", { name: "Create agent" }));
  await person.click(
    await screen.findByRole("button", { name: /Inbound reception/ }),
  );
  await person.type(
    await screen.findByLabelText("Agent name"),
    "Reception concierge",
  );
  await person.click(screen.getByRole("button", { name: "Save draft" }));
  await screen.findByText("Draft saved. Test this revision before publishing.");
  expect(
    requests.find((r) => r.path === "/agents" && r.method === "POST")?.body
      .name,
  ).toBe("Reception concierge");
  expect(
    requests.find((r) => r.path === "/agents" && r.method === "POST")?.body
      .config.template,
  ).toBe("reception");
  await person.click(await screen.findByRole("button", { name: "Test agent" }));
  expect(
    await screen.findByRole("combobox", { name: "Language model" }),
  ).toBeTruthy();
  expect(screen.getByRole("alert").textContent).toContain(
    "Complete the speech recognition connection",
  );
  expect(
    screen.getAllByRole("button", { name: "Add connection" }),
  ).toHaveLength(2);
  expect(
    screen.queryByRole("textbox", { name: "Model identifier" }),
  ).toBeNull();
});
test("connection form sends keys only on save and clears them when reopened", async () => {
  const requests = mockApi();
  const person = userEvent.setup();
  renderApp();
  await screen.findByText("Welcome back, Ada.");
  await person.click(screen.getByRole("button", { name: "Connections" }));
  await screen.findByText("No connections to display");
  await person.click(screen.getByRole("button", { name: "Add connection" }));
  await person.type(screen.getByLabelText("Connection name"), "My Deepgram");
  await person.type(screen.getByLabelText("API key"), "test-only-secret");
  expect(
    requests.filter((r) => r.path === "/connections" && r.method === "POST"),
  ).toHaveLength(0);
  await person.click(screen.getByRole("button", { name: "Save" }));
  await screen.findByText("Connection saved securely");
  expect(
    requests.find((r) => r.path === "/connections" && r.method === "POST")?.body
      .credentials.api_key,
  ).toBe("test-only-secret");
  await person.click(screen.getByRole("button", { name: "Add connection" }));
  expect((screen.getByLabelText("API key") as HTMLInputElement).value).toBe("");
});

test("existing workspace sign-in is reachable from setup and uses the login endpoint", async () => {
  const requests = mockApi(true);
  const person = userEvent.setup();
  renderApp();
  await person.click(await screen.findByRole("link", { name: "Sign in" }));
  await screen.findByText("Welcome back.");
  expect(screen.queryByLabelText("Hospital / workspace name")).toBeNull();
  await person.type(screen.getByLabelText("Work email"), "ada@example.test");
  await person.type(screen.getByLabelText("Password"), "existing-password");
  await person.click(screen.getByRole("button", { name: /Sign in/ }));
  await screen.findByText("Welcome back, Ada.");
  expect(requests.find((r) => r.path === "/login")?.body).toEqual({
    email: "ada@example.test",
    password: "existing-password",
  });
  expect(requests.some((r) => r.path === "/setup")).toBe(false);
});

test("an initialized installation presents login to signed-out users", async () => {
  mockApi(false, false);
  renderApp();
  await screen.findByText("Welcome back.");
  expect(screen.getByRole("button", { name: /Sign in/ })).toBeTruthy();
  expect(screen.queryByRole("link", { name: /Create a workspace/ })).toBeNull();
});

test("adding an ASR connection in the editor selects it and preserves agent edits", async () => {
  const requests = mockApi();
  const person = userEvent.setup();
  renderApp();
  await screen.findByText("Welcome back, Ada.");
  await person.click(screen.getByRole("button", { name: "Agents" }));
  await person.click(
    await screen.findByRole("button", { name: "Create agent" }),
  );
  await person.click(
    await screen.findByRole("button", { name: /Inbound reception/ }),
  );
  await person.type(
    await screen.findByLabelText("Agent name"),
    "Reception draft in progress",
  );
  await person.click(screen.getByRole("button", { name: /Voice & models/ }));
  expect(
    screen
      .getByRole("combobox", { name: "ASR connection" })
      .hasAttribute("disabled"),
  ).toBe(true);
  await person.click(
    screen.getAllByRole("button", { name: "Add connection" })[0],
  );
  await person.type(
    screen.getByLabelText("Connection name"),
    "Hospital Deepgram",
  );
  await person.type(screen.getByLabelText("API key"), "test-key-only");
  await person.click(screen.getByRole("button", { name: "Save" }));
  await screen.findByText("Connection saved securely");
  await waitFor(() =>
    expect(
      (
        screen.getByRole("combobox", {
          name: "ASR connection",
        }) as HTMLSelectElement
      ).value,
    ).toBe("new-connection"),
  );
  expect(
    requests.find((r) => r.path === "/connections" && r.method === "POST")?.body
      .provider,
  ).toBe("deepgram");
  await person.click(screen.getByRole("button", { name: /Identity/ }));
  expect(
    ((await screen.findByLabelText("Agent name")) as HTMLInputElement).value,
  ).toBe("Reception draft in progress");
});

test("Plivo connection sends Auth ID and token only on save", async () => {
  const requests = mockApi();
  const person = userEvent.setup();
  renderApp();
  await person.click(await screen.findByRole("button", { name: "Connections" }));
  await person.click(await screen.findByRole("button", { name: "Add connection" }));
  await person.selectOptions(screen.getByRole("combobox", { name: "Provider" }), "plivo");
  await person.type(screen.getByLabelText("Connection name"), "Plivo hospital");
  await person.type(screen.getByLabelText("Auth ID"), "MAAAAAAAAAAAAAAAAAAA");
  await person.type(screen.getByLabelText("Auth Token"), "synthetic-plivo-token");
  expect(requests.filter((r) => r.path === "/connections" && r.method === "POST")).toHaveLength(0);
  await person.click(screen.getByRole("button", { name: "Save" }));
  await screen.findByText("Connection saved securely");
  expect(requests.find((r) => r.path === "/connections" && r.method === "POST")?.body.credentials).toEqual({ auth_id: "MAAAAAAAAAAAAAAAAAAA", auth_token: "synthetic-plivo-token" });
  expect(screen.queryByDisplayValue("synthetic-plivo-token")).toBeNull();
});
