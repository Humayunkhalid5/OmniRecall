import { ExternalLink, Image as ImageIcon, Play, Trash2, X } from "lucide-react";
import { useEffect, useState } from "react";
import { engine, EngineCallError } from "../api/engine";
import type { ItemDetail as Detail } from "../api/types";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { Notice } from "../components/Notice";
import { SourceTile, sourceKind } from "../components/SourceTile";
import {
  describeError,
  formatBytes,
  formatClock,
  formatDuration,
  formatLocalTime,
  languageName,
  sourceLabels,
  statusLabels,
} from "../lib/format";

interface Props {
  itemId: string;
  onClose: () => void;
  onDeleted: (itemId: string) => void;
}

export function ItemDetail({ itemId, onClose, onDeleted }: Props) {
  const [detail, setDetail] = useState<Detail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [preview, setPreview] = useState<string | null>(null);

  useEffect(() => {
    // The parent keys this panel by item, so state starts fresh for each one.
    let active = true;
    engine
      .getItem(itemId)
      .then((d) => {
        if (!active) return;
        setDetail(d);
        if (d.item.source_type === "screenshot" && d.item.media_status === "present") {
          engine
            .itemPreview(itemId)
            .then((url) => active && setPreview(url))
            .catch(() => active && setPreview(null));
        }
      })
      .catch((e: EngineCallError) => active && setError(e.message));
    return () => {
      active = false;
    };
  }, [itemId]);

  const remove = async () => {
    setBusy(true);
    try {
      await engine.deleteItem(itemId);
      setConfirming(false);
      onDeleted(itemId);
    } catch (e) {
      setError((e as EngineCallError).message);
    } finally {
      setBusy(false);
    }
  };

  const openOriginal = async () => {
    try {
      await engine.openSource(itemId);
    } catch (e) {
      setError((e as EngineCallError).message);
    }
  };

  const item = detail?.item;
  const meta = item?.metadata ?? {};
  const isAudio = meta.format === "audio";
  return (
    <aside className="detail" aria-label="Item details">
      <header className="detail-header">
        <span className="detail-title">
          {item && <SourceTile kind={sourceKind(item.source_type, meta.format)} />}
          <h2>{item?.source_label || (item ? sourceLabels[item.source_type] : "Loading…")}</h2>
        </span>
        <button
          type="button"
          className="ghost icon-button"
          onClick={onClose}
          aria-label="Close details"
          title="Close (Esc)"
        >
          <X size={18} aria-hidden="true" />
        </button>
      </header>
      <div className="detail-content">
        {error && <Notice tone="error">{error}</Notice>}
        {!detail && !error && (
          <p className="loading-line">
            <span className="spinner" aria-hidden="true" />
            Loading…
          </p>
        )}
        {item && detail && (
          <>
            {preview && (
              <img
                className="preview"
                src={preview}
                alt={`Screenshot${typeof meta.app === "string" ? ` of ${meta.app}` : ""}`}
              />
            )}
            <dl className="facts">
              <dt>Source</dt>
              <dd>
                {isAudio ? "Audio file" : (sourceLabels[item.source_type] ?? item.source_type)}
              </dd>
              <dt>Captured</dt>
              <dd>
                <time dateTime={item.captured_at}>{formatLocalTime(item.captured_at)}</time>
              </dd>
              <dt>Status</dt>
              <dd>
                {statusLabels[item.status]}
                {item.error_code && ` — ${describeError(item.error_code)}`}
              </dd>
              {item.source_uri && (
                <>
                  <dt>Location</dt>
                  <dd className="path">
                    {item.source_uri}
                    {!detail.source_exists && <span className="badge warn">missing</span>}
                  </dd>
                </>
              )}
              {typeof meta.app === "string" && (
                <>
                  <dt>App</dt>
                  <dd>{meta.app}</dd>
                </>
              )}
              {typeof meta.display_name === "string" && item.source_type === "screenshot" && (
                <>
                  <dt>Display</dt>
                  <dd>{meta.display_name}</dd>
                </>
              )}
              {typeof meta.last_seen_at === "string" && (
                <>
                  <dt>Still on screen</dt>
                  <dd>
                    until{" "}
                    <time dateTime={meta.last_seen_at}>{formatLocalTime(meta.last_seen_at)}</time>
                  </dd>
                </>
              )}
              {typeof meta.ocr_engine === "string" && (
                <>
                  <dt>Text read by</dt>
                  <dd>
                    {meta.ocr_engine === "tesseract" ? "Tesseract" : meta.ocr_engine}
                    {typeof meta.ocr_version === "string" && ` ${meta.ocr_version}`}
                  </dd>
                </>
              )}
              {isAudio && typeof meta.duration_s === "number" && (
                <>
                  <dt>Length</dt>
                  <dd>{formatDuration(meta.duration_s)}</dd>
                </>
              )}
              {typeof meta.transcription_engine === "string" && (
                <>
                  <dt>Transcribed by</dt>
                  <dd>
                    {meta.transcription_model === "whisper-base"
                      ? "Whisper base"
                      : String(meta.transcription_model)}{" "}
                    ({meta.transcription_engine}), on this device
                  </dd>
                </>
              )}
              {isAudio && typeof meta.language === "string" && (
                <>
                  <dt>Language</dt>
                  <dd>{languageName(meta.language)}</dd>
                </>
              )}
              {typeof meta.pages === "number" && (
                <>
                  <dt>Pages</dt>
                  <dd>{meta.pages}</dd>
                </>
              )}
              {typeof meta.bytes === "number" && (
                <>
                  <dt>Size</dt>
                  <dd>{formatBytes(meta.bytes)}</dd>
                </>
              )}
              {item.media_status === "pruned" && (
                <>
                  <dt>Image</dt>
                  <dd>Not kept (retention or text-only mode); its text is still searchable</dd>
                </>
              )}
            </dl>
            <div className="detail-actions">
              {item.source_type === "file" && detail.source_exists && (
                <button type="button" onClick={openOriginal}>
                  {isAudio ? (
                    <Play size={15} aria-hidden="true" />
                  ) : (
                    <ExternalLink size={15} aria-hidden="true" />
                  )}
                  {isAudio ? "Play recording" : "Open original"}
                </button>
              )}
              {item.source_type === "screenshot" && item.media_status === "present" && (
                <button type="button" onClick={openOriginal}>
                  <ImageIcon size={15} aria-hidden="true" />
                  Open image
                </button>
              )}
              <button type="button" className="danger" onClick={() => setConfirming(true)}>
                <Trash2 size={15} aria-hidden="true" />
                Delete
              </button>
            </div>
            <h3>
              {isAudio ? "Transcript" : "Indexed text"}{" "}
              <span className="muted">
                ({detail.chunk_count} passage{detail.chunk_count === 1 ? "" : "s"})
              </span>
            </h3>
            <div className="chunks">
              {detail.chunks.map((chunk) => (
                <p key={chunk.id} className="chunk">
                  {typeof chunk.start_ms === "number" && (
                    <span className="timestamp">
                      {formatClock(chunk.start_ms)}
                      {typeof chunk.end_ms === "number" && `–${formatClock(chunk.end_ms)}`}
                    </span>
                  )}
                  {chunk.text}
                </p>
              ))}
              {detail.chunk_count > detail.chunks.length && (
                <p className="muted">
                  Showing the first {detail.chunks.length} of {detail.chunk_count} passages.
                </p>
              )}
            </div>
          </>
        )}
      </div>
      <ConfirmDialog
        open={confirming}
        title="Delete this item?"
        body={
          <p>
            Its text, search index entries, vectors, and any media OmniRecall stored are removed
            from this device. The original file, if any, is not touched. This cannot be undone.
          </p>
        }
        confirmLabel="Delete permanently"
        destructive
        busy={busy}
        onConfirm={remove}
        onCancel={() => setConfirming(false)}
      />
    </aside>
  );
}
