import { captureState, item, status } from "./fixtures";
import { shell } from "./tauri";

/** A running engine with an indexed item and every Phase 3 call answered. */
export function engineRunning() {
  shell.commands.set("engine_state", () => ({ state: "running", pid: 42 }));
  shell.commands.set("pause_shortcut", () => ({
    shortcut: "CommandOrControl+Alt+Shift+P",
    registered: true,
  }));
  shell.methods.set("capture.state", () => captureState());
  shell.methods.set("exclusions.list", () => ({ exclusions: [] }));
  shell.methods.set("storage.usage", () => ({
    media_bytes: 0,
    media_cap_bytes: 5 * 1024 ** 3,
    screenshot_retention_days: 7,
    text_only_mode: false,
  }));
  shell.methods.set("settings.get", () => ({
    settings: {
      first_run_completed: true,
      clipboard_detect_secrets: true,
      max_file_bytes: 104_857_600,
      max_pdf_pages: 500,
      results_shown: 20,
    },
    defaults: {},
  }));
  shell.methods.set("status", () => status());
  shell.methods.set("formats.list", () => ({
    documents: [{ kind: "pdf", label: "PDF (text layer only)", extensions: [".pdf"] }],
  }));
  shell.methods.set("items.list", () => ({ items: [item()], counts: { indexed: 1 } }));
  shell.methods.set("items.get", () => ({
    item: item(),
    source_exists: true,
    chunk_count: 1,
    chunks: [
      { id: "c1", ordinal: 0, text: "error E0382: borrow of moved value", start: 0, end: 34 },
    ],
  }));
}
