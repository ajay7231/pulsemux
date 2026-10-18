import {
  cleanup,
  render as baseRender,
  screen,
  waitFor,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, test, vi } from "vitest";
import { ModelSelect } from "./ModelSelect";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
vi.mock("../../app/SessionProvider", () => ({
  useSession: () => ({ session: { workspace: { id: "hospital" } } }),
}));
const clients: QueryClient[] = [];
function render(ui: ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  clients.push(client);
  return baseRender(ui, {
    wrapper: ({ children }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    ),
  });
}
afterEach(() => {
  cleanup();
  clients.splice(0).forEach((client) => client.clear());
  vi.unstubAllGlobals();
});
test("loads account models and selects a model without typing an identifier", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(
      async () =>
        new Response(
          JSON.stringify({
            provider: "groq",
            models: [{ id: "llama-example", name: "Llama example" }],
          }),
        ),
    ),
  );
  const change = vi.fn();
  render(<ModelSelect connectionId="groq-key" value="" onChange={change} />);
  await screen.findByRole("option", { name: "Llama example" });
  await userEvent
    .setup()
    .selectOptions(screen.getByRole("combobox"), "llama-example");
  expect(change).toHaveBeenCalledWith("llama-example");
  expect(fetch).toHaveBeenCalledWith(
    "/api/connections/groq-key/models",
    expect.objectContaining({ credentials: "same-origin" }),
  );
});
test("a failed catalog can be retried and missing saved models remain visibly unavailable", async () => {
  vi.stubGlobal(
    "fetch",
    vi
      .fn()
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ detail: "Check API key permissions" }), {
          status: 422,
        }),
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            provider: "groq",
            models: [{ id: "new-model", name: "New model" }],
          }),
        ),
      ),
  );
  render(
    <ModelSelect
      connectionId="key"
      value="retired-model"
      onChange={() => {}}
    />,
  );
  await screen.findByText("Check API key permissions");
  await userEvent
    .setup()
    .click(screen.getByRole("button", { name: "Retry loading models" }));
  await screen.findByRole("option", { name: "New model" });
  expect(
    screen
      .getByRole("option", { name: /retired-model.*unavailable/ })
      .hasAttribute("disabled"),
  ).toBe(true);
});
test("changing accounts discards late results from the previous account", async () => {
  let oldResult!: (result: Response) => void;
  vi.stubGlobal(
    "fetch",
    vi
      .fn()
      .mockImplementationOnce(
        () =>
          new Promise((resolve) => {
            oldResult = resolve;
          }),
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            provider: "groq",
            models: [{ id: "gpt-4.1", name: "GPT 4.1" }],
          }),
        ),
      ),
  );
  const view = render(
    <ModelSelect connectionId="old-key" value="" onChange={() => {}} />,
  );
  view.rerender(
    <ModelSelect connectionId="new-key" value="" onChange={() => {}} />,
  );
  await screen.findByRole("option", { name: "GPT 4.1" });
  oldResult(
    new Response(
      JSON.stringify({
        provider: "groq",
        models: [{ id: "old-model", name: "Old model" }],
      }),
    ),
  );
  await waitFor(() =>
    expect(screen.queryByRole("option", { name: "Old model" })).toBeNull(),
  );
});
