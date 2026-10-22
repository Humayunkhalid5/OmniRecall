import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import axe from "axe-core";
import { beforeEach, expect, test, vi } from "vitest";
import { App } from "./App";
import { engineRunning } from "./test/engineMock";
import { shell } from "./test/tauri";

const REPORT = "OmniRecall problem report\nVersion 0.1.0 (protocol 1), Linux 6.8 x86_64\n";

beforeEach(() => {
  shell.reset();
  engineRunning();
  shell.methods.set("diagnostics.report", () => ({ report: {}, text: REPORT }));
});

async function openReportPanel() {
  render(<App />);
  await userEvent.click(await screen.findByRole("button", { name: "Settings" }));
  return screen.findByRole("region", { name: "Report a problem" });
}

test("a report is shown for reading before it is copied, and nothing is sent", async () => {
  const writeText = vi.fn(async () => {});
  Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
  const panel = await openReportPanel();
  expect(screen.getByText(/never contains your captured text/)).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Copy report" })).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Create report" }));
  const preview = await screen.findByRole("textbox", { name: "Problem report" });
  expect(preview).toHaveValue(REPORT);
  expect(preview).toHaveAttribute("readonly");
  const result = await axe.run(panel, { rules: { "color-contrast": { enabled: false } } });
  expect(result.violations.map((v) => v.id)).toEqual([]);
  await userEvent.click(screen.getByRole("button", { name: "Copy report" }));
  expect(writeText).toHaveBeenCalledWith(REPORT);
  expect(await screen.findByText("Report copied.")).toBeInTheDocument();
  // The only engine call for a report is the read-only diagnostics method.
  expect(shell.calls.filter((c) => c.method.startsWith("diagnostics"))).toEqual([
    { method: "diagnostics.report", params: {} },
  ]);
});

test("saving goes through the shell's save dialog, and the issue page opens on request", async () => {
  const opened: string[] = [];
  shell.commands.set("save_problem_report", () => ({ saved: true }));
  shell.commands.set("open_issue_page", () => {
    opened.push("issues");
    return null;
  });
  await openReportPanel();
  await userEvent.click(screen.getByRole("button", { name: "Create report" }));
  await userEvent.click(await screen.findByRole("button", { name: "Save report…" }));
  expect(await screen.findByText("Report saved.")).toBeInTheDocument();
  expect(opened).toEqual([]);
  await userEvent.click(screen.getByRole("button", { name: "Open issue page in browser" }));
  expect(opened).toEqual(["issues"]);
});

test("a cancelled save says nothing, and a failure is shown", async () => {
  shell.commands.set("save_problem_report", () => ({ cancelled: true }));
  await openReportPanel();
  await userEvent.click(screen.getByRole("button", { name: "Create report" }));
  await userEvent.click(await screen.findByRole("button", { name: "Save report…" }));
  expect(screen.queryByText("Report saved.")).not.toBeInTheDocument();
  shell.commands.set("open_issue_page", () => {
    throw { code: -1, message: "The browser could not be opened", data: { code: "open_failed" } };
  });
  await userEvent.click(screen.getByRole("button", { name: "Open issue page in browser" }));
  expect(await screen.findByText("The browser could not be opened")).toBeInTheDocument();
});
