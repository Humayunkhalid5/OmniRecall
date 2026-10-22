import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import axe from "axe-core";
import { beforeEach, expect, test } from "vitest";
import type { SearchResult } from "./api/types";
import { App } from "./App";
import { engineRunning } from "./test/engineMock";
import { ITEM_ID, item, searchResponse, status } from "./test/fixtures";
import { shell } from "./test/tauri";

async function audit(container: HTMLElement) {
  // Colour contrast needs real layout, which jsdom does not provide.
  const result = await axe.run(container, { rules: { "color-contrast": { enabled: false } } });
  return result.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.html).join(" | ")}`);
}

beforeEach(() => {
  shell.reset();
});

test("shows a restart screen with a sanitized code when the engine has failed", async () => {
  shell.commands.set("engine_state", () => ({ state: "failed", code: "crash_loop" }));
  let restarted = false;
  shell.commands.set("engine_restart", () => {
    restarted = true;
  });
  const { container } = render(<App />);
  expect(await screen.findByText("The search engine is not running")).toBeInTheDocument();
  expect(screen.getByText(/Diagnostic code: crash_loop/)).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Restart engine" }));
  expect(restarted).toBe(true);
  expect(await audit(container)).toEqual([]);
});

test("switches to the app when the supervisor reports the engine running", async () => {
  shell.commands.set("engine_state", () => ({ state: "starting" }));
  shell.methods.set("status", () => status());
  render(<App />);
  expect(await screen.findByText("Starting the search engine…")).toBeInTheDocument();
  act(() => shell.emit("engine://state", { state: "running", pid: 7 }));
  expect(await screen.findByRole("search")).toBeInTheDocument();
});

test("search shows labelled results, explains the match, and opens details", async () => {
  engineRunning();
  shell.methods.set("search", () => searchResponse());
  const { container } = render(<App />);
  const input = await screen.findByLabelText("Search your history");
  await userEvent.type(input, "moved value error{Enter}");

  const results = await screen.findByRole("list", { name: "Search results" });
  expect(within(results).getByText("Strong match")).toBeInTheDocument();
  expect(within(results).getByText("matched by keywords and meaning")).toBeInTheDocument();
  expect(within(results).getByText("+1 more passages")).toBeInTheDocument();
  expect(container.querySelector("mark")?.textContent).toBe("moved");
  const search = shell.calls.find((c) => c.method === "search");
  expect(search?.params).toEqual({ query: "moved value error", filters: {} });

  await userEvent.click(within(results).getByRole("button"));
  const detail = await screen.findByRole("complementary", { name: "Item details" });
  expect(within(detail).getByText("/home/me/borrow-notes.md")).toBeInTheDocument();
  expect(await audit(container)).toEqual([]);
});

test("search warns when nothing matched strongly and when the model is missing", async () => {
  engineRunning();
  shell.methods.set("status", () =>
    status({ model: { id: "all-minilm-l6-v2", installed: false, loaded: false } }),
  );
  shell.methods.set("search", () =>
    searchResponse({
      no_strong_match: true,
      semantic_available: false,
      results: searchResponse().results.map((r) => ({
        ...r,
        relevance: "moderate" as const,
        matched_by: "keyword" as const,
        similarity: null,
      })),
    }),
  );
  render(<App />);
  expect(await screen.findByText("Meaning-based search is off")).toBeInTheDocument();
  await userEvent.type(screen.getByLabelText("Search your history"), "E0382{Enter}");
  expect(await screen.findByText(/No strong match was found/)).toBeInTheDocument();
  expect(screen.getByText("Possible match")).toBeInTheDocument();
});

test("search explains keyword-only results while the index is repaired, then re-runs", async () => {
  engineRunning();
  let repaired = false;
  shell.methods.set("search", () =>
    repaired
      ? searchResponse()
      : searchResponse({
          semantic_available: false,
          semantic_unavailable_reason: "index_repairing",
        }),
  );
  const { container } = render(<App />);
  await userEvent.type(await screen.findByLabelText("Search your history"), "borrow{Enter}");
  expect(await screen.findByText("The search index is being repaired")).toBeInTheDocument();
  expect(screen.getByText(/Nothing you saved is lost/)).toBeInTheDocument();
  expect(await audit(container)).toEqual([]);

  repaired = true;
  act(() =>
    shell.emit("engine://notification", { method: "index.repaired", params: { vectors: 3 } }),
  );
  await waitFor(() =>
    expect(screen.queryByText("The search index is being repaired")).not.toBeInTheDocument(),
  );
});

test("search with no results suggests simpler wording", async () => {
  engineRunning();
  shell.methods.set("search", () =>
    searchResponse({ results: [], count: 0, no_strong_match: true }),
  );
  render(<App />);
  await userEvent.type(await screen.findByLabelText("Search your history"), "zzz{Enter}");
  expect(await screen.findByText("No results.")).toBeInTheDocument();
  expect(screen.getByText(/Try fewer or different words/)).toBeInTheDocument();
});

test("first run with an empty index points to import", async () => {
  engineRunning();
  shell.methods.set("status", () => status({ items: {} }));
  render(<App />);
  await userEvent.click(await screen.findByRole("button", { name: "Import something" }));
  expect(await screen.findByRole("button", { name: "Import files" })).toBeInTheDocument();
});

test("deleting from the detail panel needs confirmation and closes the panel", async () => {
  engineRunning();
  shell.methods.set("search", () => searchResponse());
  const deleted: unknown[] = [];
  shell.methods.set("items.delete", (params) => {
    deleted.push(params);
    return { item_id: ITEM_ID, status: "deleting" };
  });
  render(<App />);
  await userEvent.type(await screen.findByLabelText("Search your history"), "moved{Enter}");
  await userEvent.click(
    within(await screen.findByRole("list", { name: "Search results" })).getByRole("button"),
  );
  const detail = await screen.findByRole("complementary", { name: "Item details" });

  await userEvent.click(await within(detail).findByRole("button", { name: "Delete" }));
  const dialog = await screen.findByRole("dialog", { name: "Delete this item?" });
  await userEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
  expect(deleted).toEqual([]);

  await userEvent.click(within(detail).getByRole("button", { name: "Delete" }));
  await userEvent.click(
    within(await screen.findByRole("dialog")).getByRole("button", { name: "Delete permanently" }),
  );
  await waitFor(() => expect(deleted).toEqual([{ item_id: ITEM_ID }]));
  await waitFor(() =>
    expect(screen.queryByRole("complementary", { name: "Item details" })).not.toBeInTheDocument(),
  );
});

test("library imports through the shell dialog and reports the outcome", async () => {
  engineRunning();
  shell.commands.set("import_files", () => ({
    queued: 2,
    duplicates: 1,
    rejected: [{ name: "photo.heic", code: "unsupported_format" }],
    item_ids: [],
  }));
  const { container } = render(<App />);
  await userEvent.click(await screen.findByRole("button", { name: "Library" }));
  await userEvent.click(await screen.findByRole("button", { name: "Import files" }));
  expect(
    await screen.findByText("2 queued for indexing, 1 already imported, 1 not imported."),
  ).toBeInTheDocument();
  expect(screen.getByText("photo.heic: This file type is not supported.")).toBeInTheDocument();
  expect(screen.getByText("borrow-notes.md")).toBeInTheDocument();
  expect(await audit(container)).toEqual([]);
});

test("dropped files are reported in the library", async () => {
  engineRunning();
  render(<App />);
  await screen.findByRole("search");
  act(() =>
    shell.emit("import://result", {
      ok: true,
      summary: { queued: 3, duplicates: 0, rejected: [], item_ids: [] },
    }),
  );
  expect(await screen.findByText("3 queued for indexing.")).toBeInTheDocument();
});

test("pasted text is imported with an optional title", async () => {
  engineRunning();
  const imports: unknown[] = [];
  shell.methods.set("items.import_text", (params) => {
    imports.push(params);
    return { item: item({ source_type: "text" }), created: true };
  });
  render(<App />);
  await userEvent.click(await screen.findByRole("button", { name: "Library" }));
  await userEvent.click(await screen.findByRole("button", { name: "Paste text" }));
  const dialog = await screen.findByRole("dialog", { name: "Paste text" });
  await userEvent.click(within(dialog).getByRole("button", { name: "Add to index" }));
  expect(within(dialog).getByText("Paste or type some text first.")).toBeInTheDocument();
  await userEvent.type(within(dialog).getByLabelText("Title (optional)"), "Standup");
  await userEvent.type(within(dialog).getByLabelText("Text"), "ship the release on friday");
  await userEvent.click(within(dialog).getByRole("button", { name: "Add to index" }));
  await waitFor(() =>
    expect(imports).toEqual([{ text: "ship the release on friday", label: "Standup" }]),
  );
  expect(await screen.findByText("1 queued for indexing.")).toBeInTheDocument();
});

test("failed items show the reason and can be retried", async () => {
  engineRunning();
  shell.methods.set("items.list", () => ({
    items: [item({ status: "failed", error_code: "malformed_file" })],
    counts: { failed: 1 },
  }));
  const retried: unknown[] = [];
  shell.methods.set("items.retry", (params) => {
    retried.push(params);
    return { item_id: ITEM_ID };
  });
  render(<App />);
  await userEvent.click(await screen.findByRole("button", { name: "Library" }));
  expect(await screen.findByText("The file appears to be damaged.")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Retry" }));
  await waitFor(() => expect(retried).toEqual([{ item_id: ITEM_ID }]));
});

test("settings show model setup, storage, the encryption notice, and guarded clear", async () => {
  engineRunning();
  shell.methods.set("models.list", () => ({
    models_dir: "/data/models",
    models: [
      {
        id: "all-minilm-l6-v2",
        kind: "embedding",
        name: "all-MiniLM-L6-v2",
        version: "1",
        license: "Apache-2.0",
        license_url: "https://www.apache.org/licenses/LICENSE-2.0",
        upstream: "https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2",
        download_url: "https://example.invalid/onnx.tar.gz",
        size_bytes: 83_178_821,
        installed: false,
        install: null,
      },
    ],
  }));
  shell.methods.set("settings.get", () => ({
    settings: {
      first_run_completed: true,
      max_file_bytes: 104_857_600,
      max_pdf_pages: 500,
      results_shown: 20,
    },
    defaults: {},
  }));
  const downloads: unknown[] = [];
  shell.methods.set("models.download", (params) => {
    downloads.push(params);
    return { state: "downloading" };
  });
  const clears: unknown[] = [];
  shell.methods.set("index.clear", (params) => {
    clears.push(params);
    return { cleared: 2 };
  });
  const { container } = render(<App />);
  await userEvent.click(await screen.findByRole("button", { name: "Settings" }));

  expect(await screen.findByText("Not installed")).toBeInTheDocument();
  expect(screen.getByText(/Apache-2.0/)).toBeInTheDocument();
  expect(screen.getByText("Not encrypted by OmniRecall")).toBeInTheDocument();
  expect(await screen.findByLabelText("Largest file to import (MB)")).toHaveValue(100);

  await userEvent.click(screen.getByRole("button", { name: /^Download/ }));
  await waitFor(() => expect(downloads).toEqual([{ model_id: "all-minilm-l6-v2" }]));
  act(() =>
    shell.emit("engine://notification", {
      method: "models.progress",
      params: { model_id: "all-minilm-l6-v2", received: 41_589_410, total: 83_178_821 },
    }),
  );
  expect(await screen.findByRole("progressbar")).toHaveValue(50);

  await userEvent.click(screen.getByRole("button", { name: "Delete everything…" }));
  const dialog = await screen.findByRole("dialog", { name: "Delete everything in OmniRecall?" });
  expect(within(dialog).getByText(/cannot be undone/)).toBeInTheDocument();
  expect(clears).toEqual([]);
  await userEvent.click(within(dialog).getByRole("button", { name: "Delete everything" }));
  await waitFor(() => expect(clears).toEqual([{ confirm: true }]));
  expect(await screen.findByText(/Deleted 2 items/)).toBeInTheDocument();
  expect(await audit(container)).toEqual([]);
});

test("weak matches are collapsed while stronger evidence exists", async () => {
  engineRunning();
  const [strong] = searchResponse().results as [SearchResult];
  shell.methods.set("search", () =>
    searchResponse({
      count: 3,
      results: [
        strong,
        { ...strong, item_id: "w1", chunk_id: "w1c", source_label: "weak one", relevance: "weak" },
        { ...strong, item_id: "w2", chunk_id: "w2c", source_label: "weak two", relevance: "weak" },
      ],
    }),
  );
  render(<App />);
  await userEvent.type(await screen.findByLabelText("Search your history"), "moved{Enter}");
  const list = await screen.findByRole("list", { name: "Search results" });
  expect(within(list).getAllByRole("listitem")).toHaveLength(1);
  await userEvent.click(screen.getByRole("button", { name: "Show 2 weaker matches" }));
  expect(within(list).getAllByRole("listitem")).toHaveLength(3);
  expect(screen.queryByRole("button", { name: /weaker match/ })).not.toBeInTheDocument();
});
