import { useEffect, useState } from "react";
import { engine, EngineCallError } from "../api/engine";
import type { ItemDetail as Detail } from "../api/types";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { Notice } from "../components/Notice";
import {
  describeError,
  formatBytes,
  formatLocalTime,
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

  useEffect(() => {
    // The parent keys this panel by item, so state starts fresh for each one.
    let active = true;
    engine
      .getItem(itemId)
      .then((d) => active && setDetail(d))
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
  return (
    <aside className="detail" aria-label="Item details">
      <header className="detail-header">
        <h2>{item?.source_label || (item ? sourceLabels[item.source_type] : "Loading…")}</h2>
        <button type="button" className="ghost" onClick={onClose} aria-label="Close details">
          ✕
        </button>
      </header>
      {error && <Notice tone="error">{error}</Notice>}
      {!detail && !error && <p className="muted">Loading…</p>}
      {item && detail && (
        <>
          <dl className="facts">
            <dt>Source</dt>
            <dd>{sourceLabels[item.source_type] ?? item.source_type}</dd>
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
                <dd>Removed by retention policy; text kept</dd>
              </>
            )}
          </dl>
          <div className="detail-actions">
            {item.source_type === "file" && detail.source_exists && (
              <button type="button" onClick={openOriginal}>
                Open original
              </button>
            )}
            <button type="button" className="danger" onClick={() => setConfirming(true)}>
              Delete
            </button>
          </div>
          <h3>
            Indexed text{" "}
            <span className="muted">
              ({detail.chunk_count} passage{detail.chunk_count === 1 ? "" : "s"})
            </span>
          </h3>
          <div className="chunks">
            {detail.chunks.map((chunk) => (
              <p key={chunk.id} className="chunk">
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
