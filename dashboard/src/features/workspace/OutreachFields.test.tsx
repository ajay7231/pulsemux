import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { afterEach, expect, test, vi } from "vitest";
import { OutreachFields } from "./OutreachFields";

vi.mock("../../app/SessionProvider", () => ({
  useSession: () => ({ session: { workspace: { id: "hospital" } } }),
}));
const list = vi.hoisted(() => vi.fn());
vi.mock("../../services/platform", () => ({
  resourceService: { list },
}));
afterEach(() => { cleanup(); vi.clearAllMocks(); });

function Form({ modal }: { modal: string }) {
  const [draft, setDraft] = useState<Record<string, any>>({ contact_ids: [] });
  return <OutreachFields modal={modal} draft={draft} setDraft={setDraft}
    agents={[]} numbers={[]} input={() => <input />}
    select={() => <select><option>Choose…</option></select>} />;
}

for (const modal of ["campaign", "outbound"]) {
  test(`${modal} opens and allows eligible contact selection`, async () => {
    list.mockResolvedValue({ items: [
      { id: "eligible", name: "Test contact", phone: "+15555550100", consent: true, opted_out: false },
      { id: "ineligible", name: "No consent", phone: "+15555550101", consent: false, opted_out: false },
    ], total: 2, pages: 1, page: 1 });
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<QueryClientProvider client={client}><Form modal={modal} /></QueryClientProvider>);
    const person = userEvent.setup();
    const eligible = await screen.findByRole(modal === "campaign" ? "checkbox" : "radio", { name: /Test contact/ });
    await person.click(eligible);
    expect(screen.getByText(/1 selected/)).toBeTruthy();
    expect((screen.getByRole(modal === "campaign" ? "checkbox" : "radio", { name: /No consent/ }) as HTMLInputElement).disabled).toBe(true);
    await person.type(screen.getByRole("searchbox"), "Test");
    expect(screen.getByText(/1 selected/)).toBeTruthy();
    client.clear();
  });
}
