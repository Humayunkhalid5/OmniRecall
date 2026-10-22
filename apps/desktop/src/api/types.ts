export type ItemStatus =
  "queued" | "processing" | "indexed" | "failed" | "skipped" | "deleting" | "deleted";

export type SourceType = "text" | "clipboard" | "file" | "screenshot" | "image" | "audio";

export interface Item {
  id: string;
  source_type: SourceType;
  source_label: string | null;
  source_uri: string | null;
  captured_at: string;
  /** Relative to the app media folder; set while app-owned media exists. */
  media_uri?: string | null;
  media_status: "none" | "present" | "pruned" | "deleted";
  metadata: Record<string, unknown>;
  status: ItemStatus;
  error_code: string | null;
  skip_reason: string | null;
  updated_at: string;
}

export interface ItemDetail {
  item: Item;
  source_exists: boolean;
  chunk_count: number;
  chunks: { id: string; ordinal: number; text: string; start: number | null; end: number | null }[];
}

export type Relevance = "strong" | "moderate" | "weak";

export interface SearchResult {
  item_id: string;
  chunk_id: string;
  source_type: SourceType;
  source_label: string | null;
  source_uri: string | null;
  captured_at: string;
  app: string | null;
  snippet: string;
  highlights: [number, number][];
  score: number;
  similarity: number | null;
  matched_by: "keyword" | "semantic" | "both";
  relevance: Relevance;
  more_matches: number;
}

export interface SearchResponse {
  results: SearchResult[];
  count: number;
  semantic_available: boolean;
  no_strong_match: boolean;
  took_ms: number;
}

export interface EngineStatus {
  engine: string;
  uptime_s: number;
  items: Partial<Record<ItemStatus, number>>;
  jobs: Record<string, number>;
  queue: { capacity: number; active: number; workers_busy: number; workers: number };
  model: { id: string; installed: boolean; loaded: boolean };
  index: { chunks: number; vectors: number; table: string; pending_vector_writes: number };
  storage: {
    data_dir: string;
    db_bytes: number;
    vector_bytes: number;
    media_bytes: number;
    model_bytes: number;
  };
  encryption_at_rest: boolean;
}

export interface ModelInfo {
  id: string;
  kind: "embedding" | "transcription";
  name: string;
  version: string;
  license: string;
  license_url: string;
  upstream: string;
  download_url: string;
  size_bytes: number;
  installed: boolean;
  install: { state: string; received?: number; total?: number; error_code?: string } | null;
}

export interface ImportSummary {
  queued: number;
  duplicates: number;
  rejected: { name: string; code: string }[];
  item_ids: string[];
  cancelled?: boolean;
}

export type EngineState =
  | { state: "starting" }
  | { state: "running"; pid: number }
  | { state: "restarting"; attempt: number; delay_ms: number }
  | { state: "failed"; code: string }
  | { state: "stopped" };

export interface RpcError {
  code: number;
  message: string;
  data?: { code?: string; [key: string]: unknown };
}

export interface ConsistencyReport {
  sqlite_chunks: number;
  vector_rows: number;
  missing_vectors: number;
  orphan_vectors: number;
  pending_outbox: number;
  stuck_items: number;
  fts_ok: boolean;
  consistent: boolean;
}

export interface FormatInfo {
  kind: string;
  label: string;
  extensions: string[];
}

export interface SourceState {
  enabled: boolean;
  paused: boolean;
  active: boolean;
}

export interface CaptureState {
  paused: boolean;
  capturing: boolean;
  sources: { clipboard: SourceState; screenshot: SourceState };
  session?: { clipboard?: Record<string, number>; screenshot?: Record<string, number> };
  screenshot?: { interval_s: number; pause_on_idle_s: number; phash_threshold: number };
  ocr?: { available: boolean; engine: string; version: string | null };
}

export interface ScreenshotStatus {
  /** Why periodic capture cannot run here: "wayland" or "no_display". */
  unsupported_reason: string | null;
  permission: "not_required" | "granted" | "denied";
  last_error: string | null;
  last_capture_ms: number | null;
}

export interface Formats {
  documents: FormatInfo[];
  images?: FormatInfo[];
  ocr_available?: boolean;
}

export interface Exclusion {
  id: string;
  rule_type: "app" | "path" | "pattern";
  rule_value: string;
  enabled: boolean;
  created_at: string;
}

export interface StorageUsage {
  media_bytes: number;
  media_cap_bytes: number;
  screenshot_retention_days: number;
  text_only_mode: boolean;
}

export interface ExportResult {
  path?: string;
  item_count?: number;
  chunk_count?: number;
  media_count?: number;
  bytes?: number;
  cancelled?: boolean;
}
