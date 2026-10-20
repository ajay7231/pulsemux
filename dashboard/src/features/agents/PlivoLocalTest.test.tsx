import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { PlivoLocalTest } from "./PlivoLocalTest";
import { api } from "../../lib/api";
vi.mock("../../lib/api", () => ({ api: vi.fn() }));
beforeEach(() => {
  Object.defineProperty(HTMLDialogElement.prototype, "showModal", { configurable: true, value() { this.setAttribute("open", ""); } });
  Object.defineProperty(HTMLDialogElement.prototype, "close", { configurable: true, value() { this.removeAttribute("open"); } });
});
afterEach(() => { cleanup(); vi.resetAllMocks(); });
test("prepares an authenticated command without starting a call or microphone", async () => {
  vi.mocked(api).mockResolvedValue({call_id:"call",command:"plivo voice streams test --to 'ws://localhost/test?token=synthetic' --bidirectional",expires_at:Date.now()/1000+300});
  render(<PlivoLocalTest agentId="agent" />);
  await userEvent.click(screen.getByRole("button",{name:"Plivo stream test"}));
  const field = await screen.findByRole("textbox", {name:"Single-use command"});
  expect((field as HTMLTextAreaElement).readOnly).toBe(true);
  expect((field as HTMLTextAreaElement).value).toContain("--bidirectional");
  expect(api).toHaveBeenCalledExactlyOnceWith("/agents/agent/plivo-test", "POST");
});
test("shows the server's disabled-test explanation", async () => {
  vi.mocked(api).mockRejectedValue(new Error("Local tests are disabled"));
  render(<PlivoLocalTest agentId="agent" />);
  await userEvent.click(screen.getByRole("button",{name:"Plivo stream test"}));
  expect((await screen.findByRole("alert")).textContent).toBe("Local tests are disabled");
  expect(screen.queryByRole("textbox")).toBeNull();
});
