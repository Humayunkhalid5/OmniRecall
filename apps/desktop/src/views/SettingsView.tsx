import { useCallback, useEffect, useState } from "react";
import { engine, EngineCallError, type EngineNotification } from "../api/engine";
import type { ConsistencyReport, EngineStatus, ModelInfo } from "../api/types";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { Notice } from "../components/Notice";
import type { CaptureControls } from "../hooks/useCapture";
import { useEngineEvents } from "../hooks/useEngine";
import { describeError, formatBytes } from "../lib/format";
import { CapturePanel, DataPanel, ExclusionsPanel } from "./PrivacySettings";

interface Props {
  status: EngineStatus | null;
  capture: CaptureControls;
  refreshKey: number;
  onChanged: () => void;
}

export function SettingsView({ status, capture, refreshKey, onChanged }: Props) {
  return (
    <section className="settings" aria-label="Settings">
      <CapturePanel controls={capture} />
      <ExclusionsPanel />
      <DataPanel refreshKey={refreshKey} />
      <ModelsPanel onChanged={onChanged} />
      <LimitsPanel />
      <StoragePanel status={status} />
      <IndexPanel onChanged={onChanged} />
      <ReportPanel />
    </section>
  );
}

const USABLE_KINDS: readonly string[] = ["embedding", "transcription"];
const MODEL_PURPOSE: Record<string, string> = {
  embedding: "Meaning-based search",
  transcription: "Turns imported audio notes into searchable text",
};

interface Progress {
  received: number;
  total: number;
}

function ModelsPanel({ onChanged }: { onChanged: () => void }) {
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [progress, setProgress] = useState<Record<string, Progress>>({});
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const load = useCallback(
    () =>
      engine
        .models()
        .then((r) => setModels(r.models.filter((m) => USABLE_KINDS.includes(m.kind))))
        .catch((e: EngineCallError) => setError(e.message)),
    [],
  );

  useEffect(() => {
    void load();
  }, [load]);

  useEngineEvents(
    useCallback(
      (note: EngineNotification) => {
        const id = note.params.model_id as string | undefined;
        if (!id) return;
        if (note.method === "models.progress") {
          setProgress((p) => ({
            ...p,
            [id]: { received: Number(note.params.received), total: Number(note.params.total) },
          }));
        } else if (note.method === "models.installed" || note.method === "models.failed") {
          setProgress((p) => Object.fromEntries(Object.entries(p).filter(([key]) => key !== id)));
          setBusy(null);
          if (note.method === "models.failed") {
            setError(`Model setup failed: ${describeError(note.params.code as string)}`);
          }
          void load();
          onChanged();
        }
      },
      [load, onChanged],
    ),
  );

  const download = async (model: ModelInfo) => {
    setError(null);
    setBusy(model.id);
    try {
      await engine.downloadModel(model.id);
      setProgress((p) => ({ ...p, [model.id]: { received: 0, total: model.size_bytes } }));
    } catch (e) {
      setBusy(null);
      setError((e as EngineCallError).message);
    }
  };

  const installFile = async (model: ModelInfo) => {
    setError(null);
    setBusy(model.id);
    try {
      const result = await engine.installModelFile(model.id);
      if (!result.cancelled) {
        await load();
        onChanged();
      }
    } catch (e) {
      setError((e as EngineCallError).message);
    } finally {
      setBusy(null);
    }
  };

  const cancel = async (model: ModelInfo) => {
    try {
      await engine.cancelModel(model.id);
    } catch (e) {
      setError((e as EngineCallError).message);
    }
  };

  return (
    <section className="panel" aria-labelledby="models-heading">
      <h2 id="models-heading">Local models</h2>
      <p className="muted">
        Models run on this device. Downloading contacts the listed source once; nothing you import
        is sent anywhere.
      </p>
      {error && <Notice tone="error">{error}</Notice>}
      <ul className="models">
        {models.map((model) => {
          const p = progress[model.id];
          const downloading = Boolean(p);
          const pct = p && p.total > 0 ? Math.round((p.received / p.total) * 100) : 0;
          return (
            <li key={model.id} className="model">
              <div className="model-head">
                <strong>{model.name}</strong>
                <span className={`badge ${model.installed ? "rel-strong" : "rel-weak"}`}>
                  {model.installed ? "Installed" : "Not installed"}
                </span>
              </div>
              <p className="muted">
                {MODEL_PURPOSE[model.kind] ?? model.kind} · {formatBytes(model.size_bytes)} ·
                License <span title={model.license_url}>{model.license}</span>
              </p>
              <p className="muted small">Source: {model.download_url}</p>
              {p && (
                <div className="progress-row">
                  <progress max={100} value={pct} aria-label={`Downloading ${model.name}`} />
                  <span>
                    {formatBytes(p.received)} of {formatBytes(p.total)}
                  </span>
                  <button type="button" onClick={() => void cancel(model)}>
                    Cancel
                  </button>
                </div>
              )}
              {!model.installed && !downloading && (
                <div className="row-actions">
                  <button
                    type="button"
                    className="primary"
                    onClick={() => void download(model)}
                    disabled={busy !== null}
                  >
                    Download ({formatBytes(model.size_bytes)})
                  </button>
                  <button
                    type="button"
                    onClick={() => void installFile(model)}
                    disabled={busy !== null}
                  >
                    {busy === model.id ? "Verifying…" : "Install from file…"}
                  </button>
                </div>
              )}
            </li>
          );
        })}
      </ul>
    </section>
  );
}

const MB = 1024 * 1024;

interface LimitsForm {
  max_file_mb: string;
  max_pdf_pages: string;
  max_audio_minutes: string;
  results_shown: string;
}

function LimitsPanel() {
  const [form, setForm] = useState<LimitsForm | null>(null);
  const [message, setMessage] = useState<{ tone: "success" | "error"; text: string } | null>(null);
  const [saving, setSaving] = useState(false);

  const fill = (s: Record<string, unknown>) =>
    setForm({
      max_file_mb: String(Math.round(Number(s.max_file_bytes) / MB)),
      max_pdf_pages: String(s.max_pdf_pages),
      max_audio_minutes: String(Math.round(Number(s.max_audio_seconds) / 60)),
      results_shown: String(s.results_shown),
    });

  useEffect(() => {
    engine
      .getSettings()
      .then((r) => fill(r.settings))
      .catch((e: EngineCallError) => setMessage({ tone: "error", text: e.message }));
  }, []);

  if (!form) return null;

  const save = async () => {
    setSaving(true);
    setMessage(null);
    try {
      const result = await engine.updateSettings({
        max_file_bytes: Math.round(Number(form.max_file_mb) * MB),
        max_pdf_pages: Number(form.max_pdf_pages),
        max_audio_seconds: Math.round(Number(form.max_audio_minutes) * 60),
        results_shown: Number(form.results_shown),
      });
      fill(result.settings);
      setMessage({ tone: "success", text: "Saved." });
    } catch (e) {
      setMessage({ tone: "error", text: (e as EngineCallError).message });
    } finally {
      setSaving(false);
    }
  };

  const field = (key: keyof LimitsForm, label: string, min: number, max: number) => (
    <div className="field">
      <label htmlFor={`limit-${key}`}>{label}</label>
      <input
        id={`limit-${key}`}
        type="number"
        inputMode="numeric"
        min={min}
        max={max}
        required
        value={form[key]}
        onChange={(event) => setForm({ ...form, [key]: event.target.value })}
      />
    </div>
  );

  return (
    <section className="panel" aria-labelledby="limits-heading">
      <h2 id="limits-heading">Import and search limits</h2>
      <form
        className="limits"
        onSubmit={(event) => {
          event.preventDefault();
          void save();
        }}
      >
        {field("max_file_mb", "Largest file to import (MB)", 1, 2048)}
        {field("max_pdf_pages", "Most PDF pages to read", 1, 10000)}
        {field("max_audio_minutes", "Longest recording to transcribe (minutes)", 1, 720)}
        {field("results_shown", "Search results to show", 1, 200)}
        <div className="row-actions">
          <button type="submit" disabled={saving}>
            {saving ? "Saving…" : "Save limits"}
          </button>
        </div>
      </form>
      {message && <Notice tone={message.tone}>{message.text}</Notice>}
    </section>
  );
}

function StoragePanel({ status }: { status: EngineStatus | null }) {
  const [error, setError] = useState<string | null>(null);
  const storage = status?.storage;
  return (
    <section className="panel" aria-labelledby="storage-heading">
      <h2 id="storage-heading">Storage</h2>
      {storage ? (
        <>
          <dl className="facts">
            <dt>Search database</dt>
            <dd>{formatBytes(storage.db_bytes)}</dd>
            <dt>Vector index</dt>
            <dd>{formatBytes(storage.vector_bytes)}</dd>
            <dt>Saved media</dt>
            <dd>{formatBytes(storage.media_bytes)}</dd>
            <dt>Models</dt>
            <dd>{formatBytes(storage.model_bytes)}</dd>
            <dt>Location</dt>
            <dd className="path">{storage.data_dir}</dd>
          </dl>
          <button
            type="button"
            onClick={() =>
              engine.revealDataDir().catch((e: EngineCallError) => setError(e.message))
            }
          >
            Show data folder
          </button>
        </>
      ) : (
        <p className="muted">Loading…</p>
      )}
      {error && <Notice tone="error">{error}</Notice>}
      {status && !status.encryption_at_rest && (
        <Notice tone="info" title="Not encrypted by OmniRecall">
          Your index is stored unencrypted in your user profile. It is protected by your
          account&apos;s file permissions and any disk encryption you have turned on, such as
          BitLocker, FileVault, or LUKS.
        </Notice>
      )}
    </section>
  );
}

function IndexPanel({ onChanged }: { onChanged: () => void }) {
  const [report, setReport] = useState<ConsistencyReport | null>(null);
  const [busy, setBusy] = useState<"verify" | "rebuild" | "clear" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [confirm, setConfirm] = useState<"rebuild" | "clear" | null>(null);
  const [cleared, setCleared] = useState<number | null>(null);

  const run = async (action: "verify" | "rebuild" | "clear") => {
    setBusy(action);
    setError(null);
    setCleared(null);
    try {
      if (action === "verify") setReport(await engine.verifyIndex());
      else if (action === "rebuild") setReport(await engine.rebuildIndex());
      else {
        const result = await engine.clearIndex();
        setReport(null);
        setCleared(result.cleared);
      }
      if (action !== "verify") onChanged();
    } catch (e) {
      setError((e as EngineCallError).message);
    } finally {
      setBusy(null);
      setConfirm(null);
    }
  };

  return (
    <section className="panel" aria-labelledby="index-heading">
      <h2 id="index-heading">Index maintenance</h2>
      <div className="row-actions">
        <button type="button" onClick={() => void run("verify")} disabled={busy !== null}>
          {busy === "verify" ? "Checking…" : "Check index"}
        </button>
        <button type="button" onClick={() => setConfirm("rebuild")} disabled={busy !== null}>
          Rebuild search vectors
        </button>
        <button
          type="button"
          className="danger"
          onClick={() => setConfirm("clear")}
          disabled={busy !== null}
        >
          Delete everything…
        </button>
      </div>
      {error && <Notice tone="error">{error}</Notice>}
      {cleared !== null && (
        <Notice tone="success">
          Deleted {cleared} item{cleared === 1 ? "" : "s"} and all of their index data.
        </Notice>
      )}
      {report && (
        <Notice tone={report.consistent ? "success" : "warning"} title="Index check">
          {report.consistent
            ? `Everything matches: ${report.sqlite_chunks} passages, ${report.vector_rows} vectors.`
            : `${report.missing_vectors} missing vectors, ${report.orphan_vectors} leftover vectors, ` +
              `${report.pending_outbox} pending writes, ${report.stuck_items} stuck items` +
              `${report.fts_ok ? "" : ", keyword index damaged"}. Rebuild search vectors to repair.`}
        </Notice>
      )}
      <ConfirmDialog
        open={confirm === "rebuild"}
        title="Rebuild search vectors?"
        body={
          <p>
            Every passage is embedded again with the local model. Your items are kept. This can take
            several minutes for a large index.
          </p>
        }
        confirmLabel="Rebuild"
        busy={busy === "rebuild"}
        onConfirm={() => void run("rebuild")}
        onCancel={() => setConfirm(null)}
      />
      <ConfirmDialog
        open={confirm === "clear"}
        title="Delete everything in OmniRecall?"
        destructive
        body={
          <>
            <p>
              This permanently deletes every imported item, its extracted text, its search vectors,
              and any saved media from this device. It cannot be undone.
            </p>
            <p>Your original files elsewhere on disk are not touched. Models stay installed.</p>
          </>
        }
        confirmLabel="Delete everything"
        busy={busy === "clear"}
        onConfirm={() => void run("clear")}
        onCancel={() => setConfirm(null)}
      />
    </section>
  );
}

function ReportPanel() {
  const [text, setText] = useState<string | null>(null);
  const [message, setMessage] = useState<{ tone: "success" | "error"; text: string } | null>(null);
  const run = (action: () => Promise<void>) => {
    setMessage(null);
    action().catch((e: EngineCallError) => setMessage({ tone: "error", text: e.message }));
  };
  return (
    <section className="panel" aria-labelledby="report-heading">
      <h2 id="report-heading">Report a problem</h2>
      <p>
        A problem report lists the app version, your system, counts of items by state, error codes,
        and recent warnings. It never contains your captured text, searches, file names, app names,
        or exclusions. Nothing is sent: read it, then copy or save it and attach it to an issue if
        you choose.
      </p>
      <div className="row-actions">
        <button
          type="button"
          onClick={() => run(async () => setText((await engine.problemReport()).text))}
        >
          {text === null ? "Create report" : "Create again"}
        </button>
        {text !== null && (
          <>
            <button
              type="button"
              onClick={() =>
                run(async () => {
                  await navigator.clipboard.writeText(text);
                  setMessage({ tone: "success", text: "Report copied." });
                })
              }
            >
              Copy report
            </button>
            <button
              type="button"
              onClick={() =>
                run(async () => {
                  const result = await engine.saveProblemReport();
                  if (result.saved) setMessage({ tone: "success", text: "Report saved." });
                })
              }
            >
              Save report…
            </button>
          </>
        )}
        <button type="button" onClick={() => run(() => engine.openIssuePage().then(() => {}))}>
          Open issue page in browser
        </button>
      </div>
      {text !== null && (
        <textarea
          className="report-preview"
          aria-label="Problem report"
          readOnly
          value={text}
          rows={12}
        />
      )}
      {message && <Notice tone={message.tone}>{message.text}</Notice>}
    </section>
  );
}
