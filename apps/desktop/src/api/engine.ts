import { invoke } from "@tauri-apps/api/core";
import { listen, type UnlistenFn } from "@tauri-apps/api/event";
import type {
  CaptureState,
  ConsistencyReport,
  EngineState,
  EngineStatus,
  Exclusion,
  ExportResult,
  Formats,
  ImportSummary,
  Item,
  ItemDetail,
  ItemStatus,
  ModelInfo,
  RecoveryReport,
  RpcError,
  ScreenshotStatus,
  SearchResponse,
  SourceType,
  StorageUsage,
} from "./types";

export class EngineCallError extends Error {
  readonly code: string;
  readonly rpc: RpcError;

  constructor(rpc: RpcError) {
    super(rpc.message);
    this.rpc = rpc;
    this.code = rpc.data?.code ?? String(rpc.code);
  }
}

function toError(raw: unknown): EngineCallError {
  if (raw && typeof raw === "object" && "message" in raw) {
    return new EngineCallError(raw as RpcError);
  }
  return new EngineCallError({ code: -1, message: String(raw), data: { code: "unknown" } });
}

async function call<T>(method: string, params: Record<string, unknown> = {}): Promise<T> {
  try {
    return await invoke<T>("engine_call", { method, params });
  } catch (raw) {
    throw toError(raw);
  }
}

async function command<T>(name: string, args: Record<string, unknown> = {}): Promise<T> {
  try {
    return await invoke<T>(name, args);
  } catch (raw) {
    throw toError(raw);
  }
}

export interface SearchFilters {
  source_types?: SourceType[];
  /** Imported file kinds, such as "audio". */
  formats?: string[];
  captured_after?: string;
  captured_before?: string;
}

export const engine = {
  state: () => command<EngineState>("engine_state"),
  restart: () => command<null>("engine_restart"),
  status: () => call<EngineStatus>("status"),
  search: (query: string, filters: SearchFilters = {}) =>
    call<SearchResponse>("search", { query, filters }),
  formats: () => call<Formats>("formats.list"),
  listItems: (status?: ItemStatus[], limit = 100, offset = 0) =>
    call<{ items: Item[]; counts: Partial<Record<ItemStatus, number>> }>("items.list", {
      ...(status ? { status } : {}),
      limit,
      offset,
    }),
  getItem: (itemId: string) => call<ItemDetail>("items.get", { item_id: itemId }),
  importText: (text: string, label?: string) =>
    call<{ item: Item; created: boolean }>("items.import_text", label ? { text, label } : { text }),
  deleteItem: (itemId: string) =>
    call<{ item_id: string; status: ItemStatus }>("items.delete", { item_id: itemId }),
  retryItem: (itemId: string) => call<{ item_id: string }>("items.retry", { item_id: itemId }),
  cancelItem: (itemId: string) => call<{ item_id: string }>("jobs.cancel", { item_id: itemId }),
  verifyIndex: () => call<ConsistencyReport>("index.verify"),
  rebuildIndex: () => call<ConsistencyReport>("index.rebuild"),
  clearIndex: () => call<{ cleared: number }>("index.clear", { confirm: true }),
  recoverDatabase: () => call<RecoveryReport>("database.recover", { confirm: true }),
  resetDatabase: () => call<{ media_removed: number }>("database.reset", { confirm: true }),
  getSettings: () =>
    call<{ settings: Record<string, unknown>; defaults: Record<string, unknown> }>("settings.get"),
  updateSettings: (changes: Record<string, unknown>) =>
    call<{ settings: Record<string, unknown> }>("settings.update", { changes }),
  models: () => call<{ models: ModelInfo[]; models_dir: string }>("models.list"),
  downloadModel: (modelId: string) =>
    call<{ state: string }>("models.download", { model_id: modelId }),
  cancelModel: (modelId: string) => call<null>("models.cancel", { model_id: modelId }),
  installModelFile: (modelId: string) =>
    command<{ installed?: boolean; cancelled?: boolean }>("install_model_file", { modelId }),
  importFiles: () => command<ImportSummary>("import_files"),
  importFolder: () => command<ImportSummary>("import_folder"),
  openSource: (itemId: string) => command<null>("open_item_source", { itemId }),
  revealDataDir: () => command<null>("reveal_data_dir"),
  captureState: () => call<CaptureState>("capture.state"),
  setSource: (
    sourceType: "clipboard" | "screenshot",
    change: { enabled?: boolean; paused?: boolean },
  ) => call<CaptureState>("capture.set_source", { source_type: sourceType, ...change }),
  pauseCapture: (paused: boolean) => call<CaptureState>("capture.pause", { paused }),
  exclusions: () => call<{ exclusions: Exclusion[] }>("exclusions.list"),
  addExclusion: (ruleType: "app" | "pattern", value: string) =>
    call<{ id: string; exclusions: Exclusion[] }>("exclusions.add", {
      rule_type: ruleType,
      rule_value: value,
    }),
  setExclusionEnabled: (id: string, enabled: boolean) =>
    call<{ exclusions: Exclusion[] }>("exclusions.update", { id, enabled }),
  removeExclusion: (id: string) => call<{ exclusions: Exclusion[] }>("exclusions.remove", { id }),
  addFolderExclusion: () =>
    command<{ exclusions?: Exclusion[]; cancelled?: boolean }>("add_folder_exclusion"),
  storageUsage: () => call<StorageUsage>("storage.usage"),
  exportData: () => command<ExportResult>("export_data"),
  pauseShortcut: () => command<{ shortcut: string; registered: boolean }>("pause_shortcut"),
  screenshotStatus: () => command<ScreenshotStatus>("screenshot_status"),
  requestScreenPermission: () => command<boolean>("request_screen_permission"),
  openScreenPermissionSettings: () => command<null>("open_screen_permission_settings"),
  itemPreview: (itemId: string) => command<string | null>("item_preview", { itemId }),
};

export interface EngineNotification {
  method: string;
  params: Record<string, unknown>;
}

export function onEngineState(handler: (state: EngineState) => void): Promise<UnlistenFn> {
  return listen<EngineState>("engine://state", (event) => handler(event.payload));
}

export function onEngineNotification(
  handler: (note: EngineNotification) => void,
): Promise<UnlistenFn> {
  return listen<EngineNotification>("engine://notification", (event) => handler(event.payload));
}

export function onImportResult(
  handler: (result: { ok: boolean; summary?: ImportSummary; error?: RpcError }) => void,
): Promise<UnlistenFn> {
  return listen("import://result", (event) =>
    handler(event.payload as { ok: boolean; summary?: ImportSummary; error?: RpcError }),
  );
}
