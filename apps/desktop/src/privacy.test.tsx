import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import axe from "axe-core";
import { beforeEach, expect, test } from "vitest";
import { App } from "./App";
import type { Exclusion } from "./api/types";
import { engineRunning } from "./test/engineMock";
import { captureState } from "./test/fixtures";
import { shell } from "./test/tauri";

async function audit(container: HTMLElement) {
  const result = await axe.run(container, { rules: { "color-contrast": { enabled: false } } });
  return result.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.html).join(" | ")}`);
}

beforeEach(() => {
  shell.reset();
  engineRunning();
});

test("first run explains capture, keeps it off, and is shown once", async () => {
  const updates: unknown[] = [];
  shell.methods.set("settings.get", () => ({
    settings: { first_run_completed: false },
    defaults: {},
  }));
  shell.methods.set("settings.update", (params) => {
    updates.push(params);
    return { settings: { first_run_completed: true } };
  });
  const { container } = render(<App />);
  expect(await screen.findByRole("heading", { name: "Welcome to OmniRecall" })).toBeInTheDocument();
  expect(screen.getByText(/Nothing, until you turn a source on/)).toBeInTheDocument();
  expect(screen.getByText(/cannot catch everything/)).toBeInTheDocument();
  expect(screen.getByText(/not encrypted by OmniRecall/)).toBeInTheDocument();
  expect(await audit(container)).toEqual([]);
  await userEvent.click(screen.getByRole("button", { name: "Continue with capture off" }));
  await waitFor(() => expect(updates).toEqual([{ changes: { first_run_completed: true } }]));
  expect(await screen.findByRole("search")).toBeInTheDocument();
  expect(shell.calls.some((c) => c.method === "capture.set_source")).toBe(false);
});

test("the header shows capture is off and links to settings", async () => {
  render(<App />);
  await userEvent.click(await screen.findByRole("button", { name: "Capture off" }));
  expect(await screen.findByRole("heading", { name: "Capture" })).toBeInTheDocument();
});

test("the indicator pauses and resumes with one action and follows engine pushes", async () => {
  let state = captureState({ enabled: true });
  shell.methods.set("capture.state", () => state);
  shell.methods.set("capture.pause", (params) => {
    state = captureState({ enabled: true }, Boolean(params.paused));
    return state;
  });
  render(<App />);
  expect(await screen.findByText("Capturing clipboard")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Pause" }));
  expect(await screen.findByText("Capture paused")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Resume" }));
  expect(await screen.findByText("Capturing clipboard")).toBeInTheDocument();
  // Paused from the tray or the shortcut: the engine pushes the new state.
  act(() =>
    shell.emit("engine://notification", {
      method: "capture.state",
      params: captureState({ enabled: true }, true),
    }),
  );
  expect(await screen.findByText("Capture paused")).toBeInTheDocument();
});

test("resume also clears a per-source pause", async () => {
  let state = captureState({ enabled: true, paused: true });
  shell.methods.set("capture.state", () => state);
  const calls: unknown[] = [];
  shell.methods.set("capture.set_source", (params) => {
    calls.push(params);
    state = captureState({ enabled: true });
    return state;
  });
  render(<App />);
  await userEvent.click(await screen.findByRole("button", { name: "Resume" }));
  await waitFor(() => expect(calls).toEqual([{ source_type: "clipboard", paused: false }]));
  expect(await screen.findByText("Capturing clipboard")).toBeInTheDocument();
});

test("clipboard capture is switched on explicitly in settings", async () => {
  let state = captureState();
  shell.methods.set("capture.state", () => state);
  const calls: unknown[] = [];
  shell.methods.set("capture.set_source", (params) => {
    calls.push(params);
    state = captureState({ enabled: Boolean(params.enabled) });
    return state;
  });
  const { container } = render(<App />);
  await userEvent.click(await screen.findByRole("button", { name: "Settings" }));
  const toggle = await screen.findByRole("switch", { name: "Clipboard" });
  expect(toggle).not.toBeChecked();
  expect(
    screen.getByText(/Text already on the clipboard when you turn this on is not saved/),
  ).toBeInTheDocument();
  await userEvent.click(toggle);
  await waitFor(() => expect(calls).toEqual([{ source_type: "clipboard", enabled: true }]));
  expect(await screen.findByRole("switch", { name: "Pause clipboard only" })).not.toBeChecked();
  expect(screen.getByText("Capturing clipboard")).toBeInTheDocument();
  expect(screen.getByText(/pauses or resumes capture from any app/)).toBeInTheDocument();
  expect(await audit(container)).toEqual([]);
});

test("exclusions can be added, switched off, and removed", async () => {
  let rules: Exclusion[] = [];
  const make = (id: string, rule_type: Exclusion["rule_type"], rule_value: string): Exclusion => ({
    id,
    rule_type,
    rule_value,
    enabled: true,
    created_at: "2026-01-01T00:00:00.000Z",
  });
  shell.methods.set("exclusions.list", () => ({ exclusions: rules }));
  shell.methods.set("exclusions.add", (params) => {
    rules = [...rules, make("r1", params.rule_type as "app", params.rule_value as string)];
    return { id: "r1", exclusions: rules };
  });
  shell.commands.set("add_folder_exclusion", () => {
    rules = [...rules, make("r2", "path", "/home/me/private")];
    return { id: "r2", exclusions: rules };
  });
  shell.methods.set("exclusions.update", (params) => {
    rules = rules.map((r) => (r.id === params.id ? { ...r, enabled: Boolean(params.enabled) } : r));
    return { exclusions: rules };
  });
  shell.methods.set("exclusions.remove", (params) => {
    rules = rules.filter((r) => r.id !== params.id);
    return { exclusions: rules };
  });
  render(<App />);
  await userEvent.click(await screen.findByRole("button", { name: "Settings" }));
  await userEvent.type(await screen.findByLabelText("App name"), "1Password");
  await userEvent.click(screen.getByRole("button", { name: "Add" }));
  const list = await screen.findByRole("list", { name: "Exclusion rules" });
  expect(within(list).getByText("1Password")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Add folder…" }));
  expect(await screen.findByText("/home/me/private")).toBeInTheDocument();
  const [firstToggle] = within(list).getAllByRole("checkbox");
  if (firstToggle) await userEvent.click(firstToggle);
  await waitFor(() => expect(rules[0]?.enabled).toBe(false));
  await userEvent.click(screen.getByRole("button", { name: "Remove app exclusion 1Password" }));
  await waitFor(() => expect(screen.queryByText("1Password")).not.toBeInTheDocument());
});

test("export runs through the save dialog and reports what was written", async () => {
  shell.commands.set("export_data", () => ({
    path: "/home/me/omnirecall-export.zip",
    item_count: 3,
    chunk_count: 5,
    media_count: 0,
    bytes: 4096,
  }));
  render(<App />);
  await userEvent.click(await screen.findByRole("button", { name: "Settings" }));
  await userEvent.click(await screen.findByRole("button", { name: "Export to zip…" }));
  expect(await screen.findByText("Export saved")).toBeInTheDocument();
  expect(screen.getByText("/home/me/omnirecall-export.zip")).toBeInTheDocument();
  expect(screen.getByText(/The file is not encrypted/)).toBeInTheDocument();
});

test("retention limits are saved", async () => {
  const updates: unknown[] = [];
  shell.methods.set("settings.update", (params) => {
    updates.push(params);
    return { settings: {} };
  });
  render(<App />);
  await userEvent.click(await screen.findByRole("button", { name: "Settings" }));
  const days = await screen.findByLabelText("Keep screenshot images for (days)");
  expect(days).toHaveValue(7);
  await userEvent.clear(days);
  await userEvent.type(days, "3");
  await userEvent.click(screen.getByRole("button", { name: "Save retention" }));
  await waitFor(() =>
    expect(updates).toEqual([
      { changes: { screenshot_retention_days: 3, media_cap_bytes: 5 * 1024 ** 3 } },
    ]),
  );
});
