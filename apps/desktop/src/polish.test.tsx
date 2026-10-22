import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import axe from "axe-core";
import { beforeEach, expect, test } from "vitest";
import { App } from "./App";
import type { SearchResponse } from "./api/types";
import { Highlighted } from "./components/Highlighted";
import { formatLocalTime } from "./lib/format";
import { engineRunning } from "./test/engineMock";
import { ITEM_ID, item, searchResponse } from "./test/fixtures";
import { shell } from "./test/tauri";

async function audit(container: HTMLElement) {
  // Colour contrast needs real layout, which jsdom does not provide.
  const result = await axe.run(container, { rules: { "color-contrast": { enabled: false } } });
  return result.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.html).join(" | ")}`);
}

beforeEach(() => {
  shell.reset();
});

test("highlights count code points, so an emoji before a match does not shift it", () => {
  // The engine's offsets are Python string indices: "🚀 " is two code points.
  const { container } = render(
    <Highlighted text="🚀 deploy failed: moved value" ranges={[[2, 8]]} />,
  );
  expect(container.querySelector("mark")?.textContent).toBe("deploy");
  expect(container.textContent).toBe("🚀 deploy failed: moved value");
});

test("highlights ignore out-of-range and overlapping spans without losing text", () => {
  const { container } = render(
    <Highlighted
      text="borrow of moved value"
      ranges={[
        [10, 15],
        [0, 6],
        [2, 4],
        [40, 50],
      ]}
    />,
  );
  const marks = [...container.querySelectorAll("mark")].map((m) => m.textContent);
  expect(marks).toEqual(["borrow", "moved"]);
  expect(container.textContent).toBe("borrow of moved value");
});

test("a slow answer to an older search never replaces the newer one", async () => {
  engineRunning();
  const pending: ((r: SearchResponse) => void)[] = [];
  shell.methods.set(
    "search",
    () =>
      new Promise<SearchResponse>((resolve) => {
        pending.push(resolve);
      }),
  );
  render(<App />);
  const input = await screen.findByLabelText("Search your history");
  // The same words, first across all sources, then only audio notes.
  await userEvent.type(input, "plumber{Enter}");
  const sources = screen.getByRole("group", { name: "Source" });
  await userEvent.click(within(sources).getByRole("button", { name: "Audio notes" }));
  await waitFor(() => expect(pending).toHaveLength(2));
  const [base] = searchResponse().results;
  if (!base) throw new Error("fixture has a result");
  act(() => pending[1]?.(searchResponse({ results: [{ ...base, source_label: "newer.m4a" }] })));
  expect(await screen.findByText("newer.m4a")).toBeInTheDocument();
  act(() => pending[0]?.(searchResponse({ results: [{ ...base, source_label: "older.md" }] })));
  await new Promise((r) => setTimeout(r, 20));
  expect(screen.queryByText("older.md")).not.toBeInTheDocument();
  expect(screen.getByText("newer.m4a")).toBeInTheDocument();
  const submit = within(screen.getByRole("search")).getByRole("button", { name: "Search" });
  expect(submit).toHaveAttribute("aria-busy", "false");
});

test("a new search can start while the previous one is still running", async () => {
  engineRunning();
  const queries: string[] = [];
  shell.methods.set("search", (params) => {
    queries.push(params.query as string);
    return new Promise<SearchResponse>(() => undefined);
  });
  render(<App />);
  const input = await screen.findByLabelText("Search your history");
  await userEvent.type(input, "first{Enter}");
  await userEvent.clear(input);
  await userEvent.type(input, "second{Enter}");
  await waitFor(() => expect(queries).toEqual(["first", "second"]));
});

test("/ and Ctrl+K jump to the search box; Escape closes the detail panel", async () => {
  engineRunning();
  shell.methods.set("search", () => searchResponse());
  render(<App />);
  await userEvent.click(await screen.findByRole("button", { name: "Library" }));
  await userEvent.click(await screen.findByRole("button", { name: "borrow-notes.md" }));
  expect(await screen.findByRole("complementary", { name: "Item details" })).toBeInTheDocument();

  fireEvent.keyDown(document.body, { key: "Escape" });
  await waitFor(() =>
    expect(screen.queryByRole("complementary", { name: "Item details" })).not.toBeInTheDocument(),
  );

  fireEvent.keyDown(document.body, { key: "k", ctrlKey: true });
  const input = await screen.findByLabelText("Search your history");
  await waitFor(() => expect(input).toHaveFocus());
  await userEvent.click(screen.getByRole("button", { name: "Settings" }));
  fireEvent.keyDown(document.body, { key: "/" });
  await waitFor(() => expect(screen.getByLabelText("Search your history")).toHaveFocus());
});

test("Escape inside a confirmation closes only the dialog, not the detail panel", async () => {
  engineRunning();
  render(<App />);
  await userEvent.click(await screen.findByRole("button", { name: "Library" }));
  await userEvent.click(await screen.findByRole("button", { name: "borrow-notes.md" }));
  const detail = await screen.findByRole("complementary", { name: "Item details" });
  await userEvent.click(within(detail).getByRole("button", { name: "Delete" }));
  expect(await screen.findByRole("dialog", { name: "Delete this item?" })).toBeInTheDocument();
  fireEvent.keyDown(document.body, { key: "Escape" });
  expect(screen.getByRole("complementary", { name: "Item details" })).toBeInTheDocument();
});

test("import results and errors can be dismissed", async () => {
  engineRunning();
  shell.commands.set("import_files", () => ({
    queued: 2,
    duplicates: 0,
    rejected: [
      { name: "a.heic", code: "unsupported_format" },
      { name: "a.heic", code: "unsupported_format" },
    ],
    item_ids: [],
  }));
  const { container } = render(<App />);
  await userEvent.click(await screen.findByRole("button", { name: "Library" }));
  await userEvent.click(await screen.findByRole("button", { name: "Import files" }));
  expect(await screen.findByText("2 queued for indexing, 2 not imported.")).toBeInTheDocument();
  expect(await audit(container)).toEqual([]);
  await userEvent.click(screen.getByRole("button", { name: "Dismiss: Import" }));
  expect(screen.queryByText(/queued for indexing/)).not.toBeInTheDocument();

  act(() =>
    shell.emit("import://result", {
      ok: false,
      error: { code: -1, message: "The folder could not be read." },
    }),
  );
  expect(await screen.findByText("The folder could not be read.")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Dismiss: Import failed" }));
  expect(screen.queryByText("The folder could not be read.")).not.toBeInTheDocument();
});

test("a recording of unknown length shows how much has been transcribed", async () => {
  engineRunning();
  shell.methods.set("items.list", () => ({
    items: [
      item({
        source_label: "interview.ogg",
        status: "processing",
        metadata: { format: "audio" },
      }),
    ],
    counts: { processing: 1 },
  }));
  render(<App />);
  await userEvent.click(await screen.findByRole("button", { name: "Library" }));
  const row = (await screen.findByRole("button", { name: "interview.ogg" })).closest(
    "tr",
  ) as HTMLElement;
  act(() =>
    shell.emit("engine://notification", {
      method: "items.progress",
      params: { item_id: ITEM_ID, stage: "transcribing", done_s: 150.2 },
    }),
  );
  expect(await within(row).findByText("Transcribing 2:30")).toBeInTheDocument();
  expect(within(row).queryByRole("progressbar")).not.toBeInTheDocument();
});

test("times from yesterday say so", () => {
  const now = new Date(2026, 9, 22, 9, 0);
  expect(formatLocalTime(new Date(2026, 9, 21, 23, 30).toISOString(), now)).toMatch(/^Yesterday, /);
  expect(formatLocalTime(new Date(2026, 9, 22, 8, 0).toISOString(), now)).toMatch(/^Today, /);
  expect(formatLocalTime(new Date(2026, 9, 20, 8, 0).toISOString(), now)).not.toMatch(
    /^(Today|Yesterday)/,
  );
});

test("the app shell passes an accessibility audit on every main view", async () => {
  engineRunning();
  const { container } = render(<App />);
  await screen.findByRole("search");
  expect(await audit(container)).toEqual([]);
  await userEvent.click(screen.getByRole("button", { name: "Library" }));
  await screen.findByRole("button", { name: "borrow-notes.md" });
  expect(await audit(container)).toEqual([]);
  await userEvent.click(screen.getByRole("button", { name: "Settings" }));
  await screen.findByRole("heading", { name: "Capture" });
  expect(await audit(container)).toEqual([]);
});
