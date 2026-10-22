import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import axe from "axe-core";
import { beforeEach, expect, test } from "vitest";
import { App } from "./App";
import type { Item, SearchResult } from "./api/types";
import { engineRunning } from "./test/engineMock";
import { ITEM_ID, item, searchResponse } from "./test/fixtures";
import { shell } from "./test/tauri";

async function audit(container: HTMLElement) {
  const result = await axe.run(container, { rules: { "color-contrast": { enabled: false } } });
  return result.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.html).join(" | ")}`);
}

function voiceMemo(overrides: Partial<Item> = {}): Item {
  return item({
    source_label: "standup.m4a",
    source_uri: "/home/me/Recordings/standup.m4a",
    metadata: {
      format: "audio",
      bytes: 2_400_000,
      duration_s: 245.2,
      codec: "aac",
      transcription_engine: "whisper.cpp",
      transcription_model: "whisper-base",
      language: "en",
    },
    ...overrides,
  });
}

beforeEach(() => {
  shell.reset();
  engineRunning();
});

test("the speech model is offered in settings with its size, license, and file install", async () => {
  shell.methods.set("models.list", () => ({
    models_dir: "/data/models",
    models: [
      {
        id: "whisper-base",
        kind: "transcription",
        name: "Whisper base (multilingual, whisper.cpp ggml)",
        version: "ggml-base",
        license: "MIT",
        license_url: "https://github.com/openai/whisper/blob/main/LICENSE",
        upstream: "https://huggingface.co/ggerganov/whisper.cpp",
        download_url: "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-base.bin",
        size_bytes: 148_897_792,
        installed: false,
        install: null,
      },
    ],
  }));
  const installs: unknown[] = [];
  shell.commands.set("install_model_file", (args) => {
    installs.push(args);
    return { installed: true };
  });
  const updates: Record<string, unknown>[] = [];
  shell.methods.set("settings.update", (params) => {
    updates.push(params);
    return { settings: { max_audio_seconds: 3600, max_file_bytes: 1, max_pdf_pages: 1 } };
  });
  shell.methods.set("settings.get", () => ({
    settings: {
      first_run_completed: true,
      max_file_bytes: 104_857_600,
      max_pdf_pages: 500,
      max_audio_seconds: 7200,
      results_shown: 20,
    },
    defaults: {},
  }));
  const { container } = render(<App />);
  await userEvent.click(await screen.findByRole("button", { name: "Settings" }));

  const model = (await screen.findByText(/Whisper base/)).closest("li") as HTMLElement;
  expect(within(model).getByText(/Turns imported audio notes into searchable text/)).toBeVisible();
  expect(
    within(model).getByText(/Turns imported audio notes into searchable text · 142 MB/),
  ).toBeVisible();
  expect(within(model).getByText("MIT")).toBeVisible();
  await userEvent.click(within(model).getByRole("button", { name: "Install from file…" }));
  await waitFor(() => expect(installs).toEqual([{ modelId: "whisper-base" }]));

  const limit = await screen.findByLabelText("Longest recording to transcribe (minutes)");
  expect(limit).toHaveValue(120);
  await userEvent.clear(limit);
  await userEvent.type(limit, "60");
  await userEvent.click(screen.getByRole("button", { name: "Save limits" }));
  await waitFor(() => expect(updates[0]?.changes).toMatchObject({ max_audio_seconds: 3600 }));
  expect(await audit(container)).toEqual([]);
});

test("the library lists audio formats and shows transcription progress", async () => {
  shell.methods.set("formats.list", () => ({
    documents: [],
    audio: [{ kind: "audio", label: "M4A audio (AAC or Apple Lossless)", extensions: [".m4a"] }],
    transcription_available: false,
  }));
  shell.methods.set("items.list", () => ({
    items: [voiceMemo({ status: "processing" })],
    counts: { processing: 1 },
  }));
  const { container } = render(<App />);
  await userEvent.click(await screen.findByRole("button", { name: "Library" }));
  const row = (await screen.findByRole("button", { name: "standup.m4a" })).closest(
    "tr",
  ) as HTMLElement;
  expect(within(row).getByText("Audio")).toBeInTheDocument();
  act(() =>
    shell.emit("engine://notification", {
      method: "items.progress",
      params: { item_id: ITEM_ID, stage: "transcribing", done_s: 98, total_s: 245, percent: 40 },
    }),
  );
  expect(await within(row).findByText(/Transcribing/)).toBeInTheDocument();
  expect(within(row).getByRole("progressbar")).toHaveValue(40);
  expect(within(row).getByRole("button", { name: "Cancel" })).toBeEnabled();

  await userEvent.click(screen.getByText("Supported formats"));
  expect(screen.getByText(/M4A audio/)).toBeVisible();
  expect(screen.getByText(/Install the speech model in Settings/)).toBeVisible();
  expect(await audit(container)).toEqual([]);
});

test("a missing speech model is explained on the failed item", async () => {
  shell.methods.set("items.list", () => ({
    items: [voiceMemo({ status: "failed", error_code: "transcription_model_missing" })],
    counts: { failed: 1 },
  }));
  render(<App />);
  await userEvent.click(await screen.findByRole("button", { name: "Library" }));
  expect(
    await screen.findByText("The speech model is not installed. Set it up in Settings → Models."),
  ).toBeInTheDocument();
});

test("an audio note shows its length, model, language, and timed transcript", async () => {
  shell.methods.set("items.list", () => ({ items: [voiceMemo()], counts: { indexed: 1 } }));
  shell.methods.set("items.get", () => ({
    item: voiceMemo(),
    source_exists: true,
    chunk_count: 2,
    chunks: [
      {
        id: "a",
        ordinal: 0,
        text: "Call the landlord.",
        start: 0,
        end: 18,
        start_ms: 0,
        end_ms: 4200,
      },
      {
        id: "b",
        ordinal: 1,
        text: "Ask about the plumber.",
        start: 19,
        end: 41,
        start_ms: 62_000,
        end_ms: 65_500,
      },
    ],
  }));
  const opened: unknown[] = [];
  shell.commands.set("open_item_source", (args) => {
    opened.push(args);
    return null;
  });
  const { container } = render(<App />);
  await userEvent.click(await screen.findByRole("button", { name: "Library" }));
  await userEvent.click(await screen.findByRole("button", { name: "standup.m4a" }));
  const panel = await screen.findByRole("complementary", { name: "Item details" });
  expect(await within(panel).findByText("4 min 5 s")).toBeInTheDocument();
  expect(
    within(panel).getByText(/Whisper base \(whisper.cpp\), on this device/),
  ).toBeInTheDocument();
  expect(within(panel).getByText("English")).toBeInTheDocument();
  expect(within(panel).getByRole("heading", { name: /Transcript/ })).toBeInTheDocument();
  expect(within(panel).getByText("1:02–1:05")).toBeInTheDocument();
  await userEvent.click(within(panel).getByRole("button", { name: "Play recording" }));
  expect(opened).toEqual([{ itemId: ITEM_ID }]);
  expect(await audit(container)).toEqual([]);
});

test("search can be limited to audio notes and shows where a passage is", async () => {
  const [base] = searchResponse().results as [SearchResult];
  const searches: Record<string, unknown>[] = [];
  shell.methods.set("search", (params) => {
    searches.push(params);
    return searchResponse({
      results: [{ ...base, source_label: "standup.m4a", start_ms: 62_000, end_ms: 65_500 }],
    });
  });
  render(<App />);
  const sources = await screen.findByRole("group", { name: "Source" });
  await userEvent.click(within(sources).getByRole("button", { name: "Audio notes" }));
  expect(within(sources).getByRole("button", { name: "Audio notes" })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  await userEvent.type(screen.getByLabelText("Search your history"), "plumber{Enter}");
  expect(await screen.findByText("at 1:02 in the recording")).toBeInTheDocument();
  expect(searches.at(-1)).toEqual({ query: "plumber", filters: { formats: ["audio"] } });
});
