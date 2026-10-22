import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import axe from "axe-core";
import { beforeEach, expect, test } from "vitest";
import { App } from "./App";
import type { ScreenshotStatus } from "./api/types";
import { engineRunning } from "./test/engineMock";
import { captureState, item } from "./test/fixtures";
import { shell } from "./test/tauri";

async function audit(container: HTMLElement) {
  const result = await axe.run(container, { rules: { "color-contrast": { enabled: false } } });
  return result.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.html).join(" | ")}`);
}

function status(overrides: Partial<ScreenshotStatus> = {}): ScreenshotStatus {
  return {
    unsupported_reason: null,
    permission: "not_required",
    last_error: null,
    last_capture_ms: null,
    ...overrides,
  };
}

async function openSettings() {
  render(<App />);
  await userEvent.click(await screen.findByRole("button", { name: "Settings" }));
}

beforeEach(() => {
  shell.reset();
  engineRunning();
});

test("screenshots are switched on explicitly and their timing is saved", async () => {
  let state = captureState();
  shell.methods.set("capture.state", () => state);
  const sourceCalls: unknown[] = [];
  shell.methods.set("capture.set_source", (params) => {
    sourceCalls.push(params);
    state = captureState({}, false, { enabled: Boolean(params.enabled) });
    state.session = { clipboard: {}, screenshot: { captured: 4, duplicate_image: 9, idle: 2 } };
    return state;
  });
  const updates: unknown[] = [];
  shell.methods.set("settings.update", (params) => {
    updates.push(params);
    return { settings: {} };
  });
  render(<App />);
  await userEvent.click(await screen.findByRole("button", { name: "Settings" }));
  const toggle = await screen.findByRole("switch", { name: "Screenshots" });
  expect(toggle).not.toBeChecked();
  expect(screen.getByText(/skipped while the screen is locked/)).toBeInTheDocument();
  await userEvent.click(toggle);
  await waitFor(() => expect(sourceCalls).toEqual([{ source_type: "screenshot", enabled: true }]));
  expect(await screen.findByText("Capturing screenshots")).toBeInTheDocument();
  expect(screen.getByRole("switch", { name: "Pause screenshots only" })).not.toBeChecked();
  const interval = screen.getByLabelText("Seconds between screenshots");
  await userEvent.clear(interval);
  await userEvent.type(interval, "60");
  const idle = screen.getByLabelText("Pause after inactivity (minutes, 0 = never)");
  await userEvent.clear(idle);
  await userEvent.type(idle, "10");
  await userEvent.click(screen.getByRole("button", { name: "Save timing" }));
  await waitFor(() =>
    expect(updates).toEqual([{ changes: { screenshot_interval_s: 60, pause_on_idle_s: 600 } }]),
  );
  expect(
    await screen.findByText(/4 captured, 9 skipped as unchanged, 2 skipped while you were away/),
  ).toBeInTheDocument();
});

test("on Wayland the switch is off and explains why", async () => {
  shell.commands.set("screenshot_status", () => status({ unsupported_reason: "wayland" }));
  await openSettings();
  const toggle = await screen.findByRole("switch", { name: "Screenshots" });
  await waitFor(() => expect(toggle).toBeDisabled());
  expect(screen.getByText(/not available on Wayland/)).toBeInTheDocument();
});

test("without Tesseract the switch is off and says what to install", async () => {
  const state = captureState();
  state.ocr = { available: false, engine: "tesseract", version: null };
  shell.methods.set("capture.state", () => state);
  await openSettings();
  expect(await screen.findByRole("switch", { name: "Screenshots" })).toBeDisabled();
  expect(screen.getByText(/Tesseract\) is not installed/)).toBeInTheDocument();
});

test("missing macOS permission offers both ways to grant it", async () => {
  shell.commands.set("screenshot_status", () => status({ permission: "denied" }));
  let asked = 0;
  let opened = 0;
  shell.commands.set("request_screen_permission", () => {
    asked += 1;
    return false;
  });
  shell.commands.set("open_screen_permission_settings", () => {
    opened += 1;
    return null;
  });
  await openSettings();
  expect(await screen.findByText("Screen recording permission needed")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Ask for permission" }));
  expect(await screen.findByText(/Screen recording is still off/)).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Open System Settings" }));
  expect(asked).toBe(1);
  expect(opened).toBe(1);
});

test("text-only mode is saved with the retention settings", async () => {
  const updates: Record<string, unknown>[] = [];
  shell.methods.set("settings.update", (params) => {
    updates.push(params);
    return { settings: {} };
  });
  await openSettings();
  const textOnly = await screen.findByRole("switch", { name: "Text only" });
  expect(textOnly).not.toBeChecked();
  await userEvent.click(textOnly);
  await userEvent.click(screen.getByRole("button", { name: "Save retention" }));
  await waitFor(() =>
    expect(updates[0]?.changes).toMatchObject({
      text_only_mode: true,
      screenshot_retention_days: 7,
    }),
  );
});

test("a screenshot's detail shows its preview, app, and OCR engine", async () => {
  const shot = item({
    source_type: "screenshot",
    source_label: "Terminal",
    source_uri: null,
    media_status: "present",
    media_uri: "screenshots/2026/01/abc.png",
    metadata: {
      app: "Terminal",
      display_name: "Built-in display",
      ocr_engine: "tesseract",
      ocr_version: "5.3.4",
      last_seen_at: "2026-01-02T03:10:00.000Z",
    },
  });
  shell.methods.set("items.list", () => ({ items: [shot], counts: { indexed: 1 } }));
  shell.methods.set("items.get", () => ({
    item: shot,
    source_exists: false,
    chunk_count: 1,
    chunks: [{ id: "c1", ordinal: 0, text: "cargo build failed", start: 0, end: 18 }],
  }));
  shell.commands.set("item_preview", () => "data:image/webp;base64,AAAA");
  const opened: unknown[] = [];
  shell.commands.set("open_item_source", (args) => {
    opened.push(args);
    return null;
  });
  const { container } = render(<App />);
  await userEvent.click(await screen.findByRole("button", { name: "Library" }));
  await userEvent.click(await screen.findByRole("button", { name: "Terminal" }));
  const preview = await screen.findByRole("img", { name: "Screenshot of Terminal" });
  expect(preview).toHaveAttribute("src", "data:image/webp;base64,AAAA");
  expect(screen.getByText("Built-in display")).toBeInTheDocument();
  expect(screen.getByText("Tesseract 5.3.4")).toBeInTheDocument();
  expect(screen.getByText("Still on screen")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Open image" }));
  expect(opened).toEqual([{ itemId: shot.id }]);
  expect(await audit(container)).toEqual([]);
});

test("a pruned screenshot says its image is gone but its text remains", async () => {
  const shot = item({
    source_type: "screenshot",
    source_label: "Browser",
    source_uri: null,
    media_status: "pruned",
    metadata: {},
  });
  shell.methods.set("items.list", () => ({ items: [shot], counts: { indexed: 1 } }));
  shell.methods.set("items.get", () => ({
    item: shot,
    source_exists: false,
    chunk_count: 1,
    chunks: [{ id: "c1", ordinal: 0, text: "quarterly plan", start: 0, end: 14 }],
  }));
  render(<App />);
  await userEvent.click(await screen.findByRole("button", { name: "Library" }));
  await userEvent.click(await screen.findByRole("button", { name: "Browser" }));
  expect(await screen.findByText(/its text is still searchable/)).toBeInTheDocument();
  expect(screen.queryByRole("img")).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Open image" })).not.toBeInTheDocument();
});
