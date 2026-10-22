import type { EngineStatus, Item, SearchResponse } from "../api/types";

export function status(overrides: Partial<EngineStatus> = {}): EngineStatus {
  return {
    engine: "running",
    uptime_s: 1,
    items: { indexed: 2 },
    jobs: {},
    queue: { capacity: 1000, active: 0, workers_busy: 0, workers: 2 },
    model: { id: "all-minilm-l6-v2", installed: true, loaded: false },
    index: {
      chunks: 4,
      vectors: 4,
      table: "chunks__all-minilm-l6-v2__384",
      pending_vector_writes: 0,
    },
    storage: {
      data_dir: "/data/omnirecall",
      db_bytes: 2048,
      vector_bytes: 4096,
      media_bytes: 0,
      model_bytes: 90_000_000,
    },
    encryption_at_rest: false,
    ...overrides,
  };
}

export const ITEM_ID = "01920000-0000-7000-8000-000000000001";

export function item(overrides: Partial<Item> = {}): Item {
  return {
    id: ITEM_ID,
    source_type: "file",
    source_label: "borrow-notes.md",
    source_uri: "/home/me/borrow-notes.md",
    captured_at: "2026-01-02T03:04:05.000Z",
    media_status: "none",
    metadata: { bytes: 1200, format: "markdown" },
    status: "indexed",
    error_code: null,
    skip_reason: null,
    updated_at: "2026-01-02T03:04:06.000Z",
    ...overrides,
  };
}

export function searchResponse(overrides: Partial<SearchResponse> = {}): SearchResponse {
  return {
    results: [
      {
        item_id: ITEM_ID,
        chunk_id: "01920000-0000-7000-8000-0000000000aa",
        source_type: "file",
        source_label: "borrow-notes.md",
        source_uri: "/home/me/borrow-notes.md",
        captured_at: "2026-01-02T03:04:05.000Z",
        app: null,
        snippet: "error E0382: borrow of moved value",
        highlights: [[23, 28]],
        score: 0.03,
        similarity: 0.61,
        matched_by: "both",
        relevance: "strong",
        more_matches: 1,
      },
    ],
    count: 1,
    semantic_available: true,
    no_strong_match: false,
    took_ms: 12,
    ...overrides,
  };
}
