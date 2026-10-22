import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import axe from "axe-core";
import { beforeEach, expect, test } from "vitest";
import { App } from "./App";
import type { RecoveryStatus } from "./api/types";
import { status } from "./test/fixtures";
import { shell } from "./test/tauri";

async function audit(container: HTMLElement) {
  const result = await axe.run(container, { rules: { "color-contrast": { enabled: false } } });
  return result.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.html).join(" | ")}`);
}

function recoveryStatus(
  reason: RecoveryStatus["database"]["reason"] = "malformed",
  state: RecoveryStatus["database"]["state"] = "damaged",
): RecoveryStatus {
  return {
    engine: "recovery",
    database: {
      state,
      reason,
      bytes: 3 * 1024 * 1024,
      path: "/home/me/.local/share/OmniRecall/db/omnirecall.sqlite",
      action: null,
    },
  };
}

/** An engine in recovery mode: only health, status and database.* answer. */
function engineInRecovery(reason: RecoveryStatus["database"]["reason"] = "malformed") {
  shell.commands.set("engine_state", () => ({ state: "running", pid: 9 }));
  shell.methods.set("status", () => recoveryStatus(reason));
}

beforeEach(() => {
  shell.reset();
});

test("a damaged database shows the recovery screen and changes nothing by itself", async () => {
  engineInRecovery();
  const { container } = render(<App />);
  expect(await screen.findByText("Your OmniRecall database is damaged")).toBeInTheDocument();
  expect(screen.getByText(/Nothing has been changed yet/)).toBeInTheDocument();
  expect(screen.getByText(/omnirecall\.sqlite \(3\.0 MB\)/)).toBeInTheDocument();
  // The normal app is not shown on a damaged database.
  expect(screen.queryByRole("search")).not.toBeInTheDocument();
  expect(shell.calls.some((c) => c.method.startsWith("database."))).toBe(false);
  expect(await audit(container)).toEqual([]);
});

test("recovering asks first, reports what was lost, then restarts", async () => {
  engineInRecovery();
  shell.methods.set("database.recover", () => ({
    copied: { items: 118, chunks: 1300 },
    unreadable_ranges: { chunks: 2 },
    dropped_orphans: 0,
    requeued: 3,
    lost: 2,
    complete: false,
    media_removed: 1,
  }));
  let restarted = false;
  shell.commands.set("engine_restart", () => {
    restarted = true;
  });
  const { container } = render(<App />);
  await userEvent.click(await screen.findByRole("button", { name: "Recover what can be read" }));

  const dialog = await screen.findByRole("dialog", { name: "Recover the database?" });
  expect(shell.calls.some((c) => c.method === "database.recover")).toBe(false);
  await userEvent.click(within(dialog).getByRole("button", { name: "Recover" }));

  expect(await screen.findByText("Recovery finished")).toBeInTheDocument();
  expect(shell.calls.find((c) => c.method === "database.recover")?.params).toEqual({
    confirm: true,
  });
  expect(
    screen.getByText(/118 items were recovered\. Some parts could not be read\./),
  ).toBeInTheDocument();
  expect(screen.getByText(/2 items lost their text/)).toBeInTheDocument();
  expect(screen.getByText(/3 imported files will be read again/)).toBeInTheDocument();
  expect(screen.getByText(/1 stored screenshot or recording/)).toBeInTheDocument();
  expect(screen.getByText(/Capture is off\. Check your exclusions/)).toBeInTheDocument();
  expect(await audit(container)).toEqual([]);

  await userEvent.click(screen.getByRole("button", { name: "Restart OmniRecall" }));
  expect(restarted).toBe(true);
});

test("starting over is destructive, needs confirming, and can be cancelled", async () => {
  engineInRecovery();
  shell.methods.set("database.reset", () => ({ media_removed: 4 }));
  render(<App />);
  await userEvent.click(await screen.findByRole("button", { name: "Start over" }));
  let dialog = await screen.findByRole("dialog", { name: "Delete everything and start over?" });
  await userEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
  await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  expect(shell.calls.some((c) => c.method === "database.reset")).toBe(false);

  await userEvent.click(screen.getByRole("button", { name: "Start over" }));
  dialog = await screen.findByRole("dialog", { name: "Delete everything and start over?" });
  const confirm = within(dialog).getByRole("button", { name: "Delete everything" });
  expect(confirm).toHaveClass("danger");
  await userEvent.click(confirm);
  expect(await screen.findByText(/OmniRecall will start empty/)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Restart OmniRecall" })).toBeInTheDocument();
});

test("an unreadable file offers only starting over, and failures are shown", async () => {
  engineInRecovery("not_a_database");
  shell.methods.set("database.reset", () => {
    throw { code: -32000, message: "The files could not be removed", data: { code: "x" } };
  });
  render(<App />);
  expect(await screen.findByText(/could not be read at all/)).toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "Recover what can be read" }),
  ).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Start over" }));
  const dialog = await screen.findByRole("dialog");
  await userEvent.click(within(dialog).getByRole("button", { name: "Delete everything" }));
  expect(await screen.findByText("That did not work")).toBeInTheDocument();
  expect(screen.getByText("The files could not be removed")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Start over" })).toBeInTheDocument();
});

test("after the restart the normal app opens", async () => {
  engineInRecovery();
  shell.methods.set("settings.get", () => ({
    settings: { first_run_completed: true },
    defaults: {},
  }));
  shell.methods.set("capture.state", () => {
    throw { code: -32601, message: "not in recovery", data: { code: "x" } };
  });
  render(<App />);
  expect(await screen.findByText("Your OmniRecall database is damaged")).toBeInTheDocument();
  shell.methods.set("status", () => status());
  act(() => shell.emit("engine://state", { state: "restarting", attempt: 1 }));
  act(() => shell.emit("engine://state", { state: "running", pid: 10 }));
  expect(await screen.findByRole("search")).toBeInTheDocument();
  expect(screen.queryByText("Your OmniRecall database is damaged")).not.toBeInTheDocument();
});

test("data from a newer version is reported and nothing is offered", async () => {
  engineInRecovery("schema_too_new");
  const { container } = render(<App />);
  expect(
    await screen.findByText("Your data was saved by a newer version of OmniRecall"),
  ).toBeInTheDocument();
  expect(screen.getByText(/Nothing has been changed/)).toBeInTheDocument();
  expect(screen.queryByRole("button")).not.toBeInTheDocument();
  expect(await audit(container)).toEqual([]);
});
