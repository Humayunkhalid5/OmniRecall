import { ClipboardPaste, FileUp, FolderUp, RotateCcw, X } from "lucide-react";
import { useCallback, useEffect, useId, useRef, useState } from "react";
import { engine, EngineCallError, type EngineNotification } from "../api/engine";
import type { FormatInfo, ImportSummary, Item, ItemStatus } from "../api/types";
import { Notice } from "../components/Notice";
import { SourceTile, sourceKind } from "../components/SourceTile";
import { useEngineEvents } from "../hooks/useEngine";
import {
  describeError,
  formatClock,
  formatLocalTime,
  sourceLabels,
  statusLabels,
} from "../lib/format";

interface Props {
  selectedId: string | null;
  onSelect: (itemId: string) => void;
  refreshKey: number;
  lastImport: ImportSummary | null;
  onDismissImport?: () => void;
  onImported: (summary: ImportSummary) => void;
  onChanged: () => void;
}

type Filter = "all" | "active" | "failed";

const FILTERS: { value: Filter; label: string; status?: ItemStatus[] }[] = [
  { value: "all", label: "All" },
  { value: "active", label: "In progress", status: ["queued", "processing", "deleting"] },
  { value: "failed", label: "Needs attention", status: ["failed", "skipped"] },
];

const PAGE = 100;

interface Progress {
  stage: string;
  percent?: number;
  /** Seconds of a recording transcribed so far, and its length when known. */
  doneS?: number;
  totalS?: number;
}

const stageLabels: Record<string, string> = {
  extracting: "Reading",
  transcribing: "Transcribing",
  chunking: "Splitting",
  embedding: "Indexing",
};

function sourceOf(item: Item): string {
  if (item.metadata.format === "audio") return "Audio";
  return sourceLabels[item.source_type] ?? item.source_type;
}

export function summarizeImport(summary: ImportSummary): string {
  const parts: string[] = [];
  if (summary.queued) parts.push(`${summary.queued} queued for indexing`);
  if (summary.duplicates) parts.push(`${summary.duplicates} already imported`);
  if (summary.rejected.length) parts.push(`${summary.rejected.length} not imported`);
  return parts.length ? `${parts.join(", ")}.` : "Nothing was imported.";
}

export function LibraryView({
  selectedId,
  onSelect,
  refreshKey,
  lastImport,
  onDismissImport,
  onImported,
  onChanged,
}: Props) {
  const [items, setItems] = useState<Item[]>([]);
  const [counts, setCounts] = useState<Partial<Record<ItemStatus, number>>>({});
  const [filter, setFilter] = useState<Filter>("all");
  const [limit, setLimit] = useState(PAGE);
  const [formats, setFormats] = useState<FormatInfo[]>([]);
  const [ocrAvailable, setOcrAvailable] = useState(true);
  const [transcriptionAvailable, setTranscriptionAvailable] = useState(true);
  const [progress, setProgress] = useState<Record<string, Progress>>({});
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [pasteOpen, setPasteOpen] = useState(false);

  const progressOf = (itemId: string) => {
    const p = progress[itemId];
    if (!p) return null;
    const label = stageLabels[p.stage] ?? p.stage;
    // Without a known length, a recording's progress is the time transcribed so far.
    const elapsed =
      p.percent === undefined && p.doneS !== undefined
        ? ` ${formatClock(p.doneS * 1000)}${p.totalS ? ` of ${formatClock(p.totalS * 1000)}` : ""}`
        : "";
    return (
      <span className="status-reason">
        {label}
        {elapsed}
        {p.percent !== undefined && (
          <>
            {" "}
            <progress max={100} value={p.percent} aria-label={`${label} progress`} /> {p.percent}%
          </>
        )}
      </span>
    );
  };

  const load = useCallback(
    () =>
      engine
        .listItems(FILTERS.find((f) => f.value === filter)?.status, limit)
        .then((result) => {
          setItems(result.items);
          setCounts(result.counts);
        })
        .catch((e: EngineCallError) => setError(e.message)),
    [filter, limit],
  );

  useEffect(() => {
    void load();
  }, [load, refreshKey]);

  // Keep the list fresh while anything is still moving through the pipeline.
  const moving = items.some((i) => ["queued", "processing", "deleting"].includes(i.status));
  useEffect(() => {
    if (!moving) return;
    const timer = setInterval(() => void load(), 1500);
    return () => clearInterval(timer);
  }, [moving, load]);

  useEffect(() => {
    engine
      .formats()
      .then((f) => {
        setFormats([...f.documents, ...(f.images ?? []), ...(f.audio ?? [])]);
        setOcrAvailable(f.ocr_available ?? false);
        setTranscriptionAvailable(f.transcription_available ?? false);
      })
      .catch(() => setFormats([]));
  }, []);

  useEngineEvents(
    useCallback((note: EngineNotification) => {
      const id = note.params.item_id as string | undefined;
      if (!id) return;
      if (note.method === "items.progress") {
        const { percent, done_s: doneS, total_s: totalS } = note.params;
        setProgress((p) => ({
          ...p,
          [id]: {
            stage: String(note.params.stage),
            percent: typeof percent === "number" ? percent : undefined,
            doneS: typeof doneS === "number" ? doneS : undefined,
            totalS: typeof totalS === "number" ? totalS : undefined,
          },
        }));
      } else {
        setProgress((p) => Object.fromEntries(Object.entries(p).filter(([key]) => key !== id)));
      }
    }, []),
  );

  const runImport = async (kind: "files" | "folder") => {
    setBusy(kind);
    setError(null);
    try {
      const summary = kind === "files" ? await engine.importFiles() : await engine.importFolder();
      if (!summary.cancelled) onImported(summary);
    } catch (e) {
      setError((e as EngineCallError).message);
    } finally {
      setBusy(null);
    }
  };

  const act = async (item: Item, action: "retry" | "cancel") => {
    setBusy(item.id);
    setError(null);
    try {
      if (action === "retry") await engine.retryItem(item.id);
      else await engine.cancelItem(item.id);
      onChanged();
    } catch (e) {
      setError((e as EngineCallError).message);
    } finally {
      setBusy(null);
    }
  };

  const total = Object.entries(counts)
    .filter(([status]) => status !== "deleted")
    .reduce((sum, [, n]) => sum + (n ?? 0), 0);
  const inProgress = (counts.queued ?? 0) + (counts.processing ?? 0);
  const needsAttention = (counts.failed ?? 0) + (counts.skipped ?? 0);

  return (
    <section className="library view" aria-label="Library">
      <div className="page-head">
        <p className="eyebrow">Library</p>
        <h2 className="page-title">Everything OmniRecall knows</h2>
        <p className="page-sub">
          Import documents, audio notes, and images. Each one is read and indexed on this device.
        </p>
      </div>
      <div className="dropzone">
        <div className="dropzone-copy">
          <span className="tile lg" aria-hidden="true">
            <FileUp size={26} strokeWidth={2.2} />
          </span>
          <div>
            <strong>Add to your library</strong>
            <p className="muted small drop-hint">
              You can also drop files or folders onto this window.
            </p>
          </div>
        </div>
        <div className="toolbar">
          <button
            type="button"
            className="primary"
            onClick={() => void runImport("files")}
            disabled={busy !== null}
          >
            <FileUp size={16} aria-hidden="true" />
            {busy === "files" ? "Choosing…" : "Import files"}
          </button>
          <button type="button" onClick={() => void runImport("folder")} disabled={busy !== null}>
            <FolderUp size={16} aria-hidden="true" />
            {busy === "folder" ? "Choosing…" : "Import folder"}
          </button>
          <button type="button" onClick={() => setPasteOpen(true)} disabled={busy !== null}>
            <ClipboardPaste size={16} aria-hidden="true" />
            Paste text
          </button>
        </div>
      </div>

      {lastImport && (
        <Notice
          tone={lastImport.rejected.length ? "warning" : "success"}
          title="Import"
          onDismiss={onDismissImport}
        >
          {summarizeImport(lastImport)}
          {lastImport.rejected.length > 0 && (
            <ul className="rejected">
              {lastImport.rejected.slice(0, 10).map((r, index) => (
                <li key={`${index}-${r.name}`}>
                  {r.name}: {describeError(r.code)}
                </li>
              ))}
              {lastImport.rejected.length > 10 && (
                <li>and {lastImport.rejected.length - 10} more</li>
              )}
            </ul>
          )}
        </Notice>
      )}
      {error && (
        <Notice tone="error" onDismiss={() => setError(null)}>
          {error}
        </Notice>
      )}

      <dl className="counts" aria-label="Index progress">
        <div>
          <dt>Items</dt>
          <dd>{total}</dd>
        </div>
        <div>
          <dt>Indexed</dt>
          <dd>{counts.indexed ?? 0}</dd>
        </div>
        <div>
          <dt>In progress</dt>
          <dd>{inProgress}</dd>
        </div>
        <div>
          <dt>Needs attention</dt>
          <dd>{needsAttention}</dd>
        </div>
      </dl>

      <div className="segmented" role="group" aria-label="Show">
        {FILTERS.map((f) => (
          <button
            key={f.value}
            type="button"
            aria-pressed={filter === f.value}
            onClick={() => {
              setFilter(f.value);
              setLimit(PAGE);
            }}
          >
            {f.label}
          </button>
        ))}
      </div>

      {items.length === 0 ? (
        <div className="empty">
          <span className="tile lg" aria-hidden="true">
            <FileUp size={26} strokeWidth={2.2} />
          </span>
          <p>{filter === "all" ? "Nothing imported yet." : "No items in this view."}</p>
        </div>
      ) : (
        <div className="table-wrap">
          <table className="items">
            <thead>
              <tr>
                <th scope="col">Item</th>
                <th scope="col">Source</th>
                <th scope="col">Added</th>
                <th scope="col">Status</th>
                <th scope="col">
                  <span className="sr-only">Actions</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {items.map((item) => (
                <tr key={item.id} className={selectedId === item.id ? "selected" : undefined}>
                  <td>
                    <span className="item-cell">
                      <SourceTile
                        kind={sourceKind(item.source_type, item.metadata.format)}
                        size="sm"
                      />
                      <button type="button" className="link" onClick={() => onSelect(item.id)}>
                        {item.source_label || sourceLabels[item.source_type]}
                      </button>
                    </span>
                  </td>
                  <td className="cell-muted">{sourceOf(item)}</td>
                  <td className="cell-muted">
                    <time dateTime={item.captured_at}>{formatLocalTime(item.captured_at)}</time>
                  </td>
                  <td>
                    <span className={`status status-${item.status}`}>
                      {statusLabels[item.status]}
                    </span>
                    {item.status === "processing" && progressOf(item.id)}
                    {item.status === "failed" && (
                      <span className="status-reason">{describeError(item.error_code)}</span>
                    )}
                    {item.status === "skipped" && (
                      <span className="status-reason">{describeError(item.skip_reason)}</span>
                    )}
                  </td>
                  <td>
                    <div className="row-actions">
                      {item.status === "failed" && item.error_code !== "source_missing" && (
                        <button
                          type="button"
                          onClick={() => void act(item, "retry")}
                          disabled={busy === item.id}
                        >
                          <RotateCcw size={14} aria-hidden="true" />
                          Retry
                        </button>
                      )}
                      {(item.status === "queued" || item.status === "processing") && (
                        <button
                          type="button"
                          className="ghost"
                          onClick={() => void act(item, "cancel")}
                          disabled={busy === item.id}
                        >
                          <X size={14} aria-hidden="true" />
                          Cancel
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {items.length >= limit && (
        <button type="button" className="show-more" onClick={() => setLimit((n) => n + PAGE)}>
          Show more
        </button>
      )}

      {formats.length > 0 && (
        <details className="formats">
          <summary>Supported formats</summary>
          <ul>
            {formats.map((f) => (
              <li key={`${f.kind}-${f.extensions[0]}`}>
                {f.label} <span className="muted">({f.extensions.join(", ")})</span>
              </li>
            ))}
          </ul>
          <p className="muted">
            Text in images is read on this computer with Tesseract OCR (English).{" "}
            {ocrAvailable
              ? "Scanned PDFs without a text layer are not read yet."
              : "Tesseract is not installed, so images cannot be imported."}
          </p>
          <p className="muted">
            Audio is transcribed on this computer with Whisper, in recordings up to the length set
            in Settings. Opus recordings (.opus, WebM) are not supported yet.{" "}
            {!transcriptionAvailable &&
              "Install the speech model in Settings → Models before importing audio."}
          </p>
        </details>
      )}

      <PasteDialog
        open={pasteOpen}
        onClose={() => setPasteOpen(false)}
        onImported={(created) => {
          setPasteOpen(false);
          onImported({
            queued: created ? 1 : 0,
            duplicates: created ? 0 : 1,
            rejected: [],
            item_ids: [],
          });
        }}
      />
    </section>
  );
}

interface PasteProps {
  open: boolean;
  onClose: () => void;
  onImported: (created: boolean) => void;
}

const MAX_PASTE_CHARS = 1_000_000;

function PasteDialog({ open, onClose, onImported }: PasteProps) {
  const ref = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  const [text, setText] = useState("");
  const [label, setLabel] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open && !dialog.open) {
      if (typeof dialog.showModal === "function") dialog.showModal();
      else dialog.setAttribute("open", "");
    }
  }, [open]);

  if (!open) return null;

  const close = () => {
    setText("");
    setLabel("");
    setError(null);
    onClose();
  };

  const submit = async () => {
    if (!text.trim()) {
      setError("Paste or type some text first.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const result = await engine.importText(text, label.trim() || undefined);
      setText("");
      setLabel("");
      onImported(result.created);
    } catch (e) {
      setError((e as EngineCallError).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <dialog
      ref={ref}
      className="dialog wide"
      aria-labelledby={titleId}
      onCancel={(event) => {
        event.preventDefault();
        close();
      }}
    >
      <form
        onSubmit={(event) => {
          event.preventDefault();
          void submit();
        }}
      >
        <h2 id={titleId}>Paste text</h2>
        <label htmlFor="paste-label">Title (optional)</label>
        <input
          id="paste-label"
          type="text"
          maxLength={200}
          value={label}
          onChange={(event) => setLabel(event.target.value)}
        />
        <label htmlFor="paste-text">Text</label>
        <textarea
          id="paste-text"
          rows={10}
          maxLength={MAX_PASTE_CHARS}
          value={text}
          onChange={(event) => setText(event.target.value)}
        />
        {error && <Notice tone="error">{error}</Notice>}
        <div className="dialog-actions">
          <button type="button" onClick={close} disabled={busy}>
            Cancel
          </button>
          <button type="submit" className="primary" disabled={busy}>
            {busy ? "Adding…" : "Add to index"}
          </button>
        </div>
      </form>
    </dialog>
  );
}
