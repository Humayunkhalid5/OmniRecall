import { useCallback, useEffect, useState } from "react";
import { engine, EngineCallError } from "../api/engine";
import type { Exclusion, ExportResult, StorageUsage } from "../api/types";
import { Notice } from "../components/Notice";
import type { CaptureControls } from "../hooks/useCapture";
import { formatBytes } from "../lib/format";

const outcomeLabels: Record<string, string> = {
  captured: "captured",
  duplicate: "already saved",
  sensitive: "dropped as possibly sensitive",
  excluded_app: "dropped from excluded apps",
  excluded_pattern: "dropped by text exclusions",
  app_unknown: "dropped because the app could not be identified",
  too_large: "dropped as too large",
  empty: "empty",
};

function shortcutLabel(shortcut: string): string {
  const mac = typeof navigator !== "undefined" && /Mac/i.test(navigator.platform);
  return shortcut
    .replace("CommandOrControl", mac ? "⌘" : "Ctrl")
    .replace("Alt", mac ? "⌥" : "Alt")
    .replace("Shift", mac ? "⇧" : "Shift")
    .split("+")
    .join(mac ? "" : "+");
}

interface CaptureProps {
  controls: CaptureControls;
}

const COUNTS_REFRESH_MS = 5000;

export function CapturePanel({ controls }: CaptureProps) {
  const { capture, error, setPaused, setSource, refresh } = controls;
  const [detectSecrets, setDetectSecrets] = useState<boolean | null>(null);
  const [shortcut, setShortcut] = useState<{ shortcut: string; registered: boolean } | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    engine
      .getSettings()
      .then((r) => setDetectSecrets(Boolean(r.settings.clipboard_detect_secrets)))
      .catch(() => setDetectSecrets(null));
    engine
      .pauseShortcut()
      .then(setShortcut)
      .catch(() => setShortcut(null));
  }, []);

  // Session counts are not pushed with state changes, so poll while visible.
  useEffect(() => {
    refresh();
    const timer = setInterval(refresh, COUNTS_REFRESH_MS);
    return () => clearInterval(timer);
  }, [refresh]);

  if (!capture) return null;
  const clipboard = capture.sources.clipboard;
  const anyEnabled = Object.values(capture.sources).some((s) => s.enabled);
  const counts = capture.session?.clipboard ?? {};
  const countText = Object.entries(counts)
    .filter(([, n]) => n > 0)
    .map(([outcome, n]) => `${n} ${outcomeLabels[outcome] ?? outcome}`)
    .join(", ");

  const toggleSecrets = async (value: boolean) => {
    try {
      await engine.updateSettings({ clipboard_detect_secrets: value });
      setDetectSecrets(value);
      setMessage(null);
    } catch (e) {
      setMessage((e as EngineCallError).message);
    }
  };

  return (
    <section className="panel" aria-labelledby="capture-heading">
      <h2 id="capture-heading">Capture</h2>
      {error && <Notice tone="error">{error}</Notice>}
      {message && <Notice tone="error">{message}</Notice>}
      <div className="switch-row">
        <div>
          <label htmlFor="clipboard-enabled" className="switch-label">
            Clipboard
          </label>
          <p className="muted small" id="clipboard-help">
            Saves text you copy from now on, so you can search it later. Text already on the
            clipboard when you turn this on is not saved. Images and files on the clipboard are
            ignored.
          </p>
        </div>
        <input
          id="clipboard-enabled"
          type="checkbox"
          role="switch"
          aria-describedby="clipboard-help"
          checked={clipboard.enabled}
          onChange={(event) => void setSource("clipboard", { enabled: event.target.checked })}
        />
      </div>
      {clipboard.enabled && (
        <div className="switch-row nested">
          <label htmlFor="clipboard-paused" className="switch-label">
            Pause clipboard only
          </label>
          <input
            id="clipboard-paused"
            type="checkbox"
            role="switch"
            checked={clipboard.paused}
            onChange={(event) => void setSource("clipboard", { paused: event.target.checked })}
          />
        </div>
      )}
      <div className="switch-row">
        <div>
          <label htmlFor="secrets" className="switch-label">
            Drop copies that look like secrets
          </label>
          <p className="muted small" id="secrets-help">
            Best effort: recognises private keys, common API tokens, card numbers, and password-like
            text. It cannot recognise every secret.
          </p>
        </div>
        <input
          id="secrets"
          type="checkbox"
          role="switch"
          aria-describedby="secrets-help"
          disabled={detectSecrets === null}
          checked={detectSecrets ?? true}
          onChange={(event) => void toggleSecrets(event.target.checked)}
        />
      </div>
      {(anyEnabled || capture.paused) && (
        <div className="row-actions">
          <button
            type="button"
            className={capture.paused ? "primary" : ""}
            onClick={() => void setPaused(!capture.paused)}
          >
            {capture.paused ? "Resume all capture" : "Pause all capture"}
          </button>
        </div>
      )}
      <p className="muted small">
        {shortcut?.registered
          ? `Shortcut: ${shortcutLabel(shortcut.shortcut)} pauses or resumes capture from any app. `
          : "A global pause shortcut is not available on this system. "}
        While any source is on, closing the window keeps OmniRecall running in the system tray; quit
        it from the tray menu.
      </p>
      {clipboard.enabled && countText && (
        <p className="muted small" aria-live="polite">
          Since the app started: {countText}.
        </p>
      )}
    </section>
  );
}

const typeLabels = { app: "App", pattern: "Text", path: "Folder" } as const;

export function ExclusionsPanel() {
  const [rules, setRules] = useState<Exclusion[]>([]);
  const [kind, setKind] = useState<"app" | "pattern">("app");
  const [value, setValue] = useState("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    engine
      .exclusions()
      .then((r) => setRules(r.exclusions))
      .catch((e: EngineCallError) => setError(e.message));
  }, []);

  const run = async (request: Promise<{ exclusions?: Exclusion[] }>) => {
    try {
      const result = await request;
      if (result.exclusions) setRules(result.exclusions);
      setError(null);
      return true;
    } catch (e) {
      setError((e as EngineCallError).message);
      return false;
    }
  };

  const add = async () => {
    if (await run(engine.addExclusion(kind, value))) setValue("");
  };

  return (
    <section className="panel" aria-labelledby="exclusions-heading">
      <h2 id="exclusions-heading">Exclusions</h2>
      <p className="muted small">
        Checked before anything is saved. <strong>App</strong>: copies made while that app is in
        front are dropped; if the app cannot be identified (for example on some Linux desktops),
        clipboard copies are dropped whenever app exclusions exist. <strong>Text</strong>: copies
        containing that text are dropped (exact text, not case-sensitive). <strong>Folder</strong>:
        files in that folder are never imported.
      </p>
      <form
        className="exclusion-form"
        onSubmit={(event) => {
          event.preventDefault();
          void add();
        }}
      >
        <label htmlFor="exclusion-kind" className="sr-only">
          Exclusion type
        </label>
        <select
          id="exclusion-kind"
          value={kind}
          onChange={(event) => setKind(event.target.value as "app" | "pattern")}
        >
          <option value="app">App name</option>
          <option value="pattern">Text</option>
        </select>
        <label htmlFor="exclusion-value" className="sr-only">
          {kind === "app" ? "App name" : "Text to exclude"}
        </label>
        <input
          id="exclusion-value"
          type="text"
          maxLength={500}
          placeholder={kind === "app" ? "e.g. 1Password" : "e.g. Project Falcon"}
          value={value}
          onChange={(event) => setValue(event.target.value)}
        />
        <button type="submit" disabled={!value.trim()}>
          Add
        </button>
        <button type="button" onClick={() => void run(engine.addFolderExclusion())}>
          Add folder…
        </button>
      </form>
      {error && <Notice tone="error">{error}</Notice>}
      {rules.length === 0 ? (
        <p className="muted">No exclusions yet.</p>
      ) : (
        <ul className="exclusions" aria-label="Exclusion rules">
          {rules.map((rule) => (
            <li key={rule.id}>
              <span className="badge">{typeLabels[rule.rule_type]}</span>
              <span className={`rule-value ${rule.enabled ? "" : "muted"}`}>{rule.rule_value}</span>
              <label className="small">
                <input
                  type="checkbox"
                  checked={rule.enabled}
                  onChange={(event) =>
                    void run(engine.setExclusionEnabled(rule.id, event.target.checked))
                  }
                />{" "}
                On
              </label>
              <button
                type="button"
                className="ghost"
                aria-label={`Remove ${typeLabels[rule.rule_type].toLowerCase()} exclusion ${rule.rule_value}`}
                onClick={() => void run(engine.removeExclusion(rule.id))}
              >
                Remove
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

const GB = 1024 ** 3;

export function DataPanel({ refreshKey }: { refreshKey: number }) {
  const [usage, setUsage] = useState<StorageUsage | null>(null);
  const [days, setDays] = useState("");
  const [capGb, setCapGb] = useState("");
  const [message, setMessage] = useState<{ tone: "success" | "error"; text: string } | null>(null);
  const [exporting, setExporting] = useState(false);
  const [exported, setExported] = useState<ExportResult | null>(null);

  const load = useCallback(
    () =>
      engine
        .storageUsage()
        .then((u) => {
          setUsage(u);
          setDays(String(u.screenshot_retention_days));
          setCapGb(String(Math.round((u.media_cap_bytes / GB) * 10) / 10));
        })
        .catch((e: EngineCallError) => setMessage({ tone: "error", text: e.message })),
    [],
  );

  useEffect(() => {
    void load();
  }, [load, refreshKey]);

  const save = async () => {
    try {
      await engine.updateSettings({
        screenshot_retention_days: Number(days),
        media_cap_bytes: Math.round(Number(capGb) * GB),
      });
      await load();
      setMessage({ tone: "success", text: "Saved. Older media beyond these limits was removed." });
    } catch (e) {
      setMessage({ tone: "error", text: (e as EngineCallError).message });
    }
  };

  const runExport = async () => {
    setExporting(true);
    setExported(null);
    setMessage(null);
    try {
      const result = await engine.exportData();
      if (!result.cancelled) setExported(result);
    } catch (e) {
      setMessage({ tone: "error", text: (e as EngineCallError).message });
    } finally {
      setExporting(false);
    }
  };

  return (
    <section className="panel" aria-labelledby="data-heading">
      <h2 id="data-heading">Your data</h2>
      <h3>Export</h3>
      <p className="muted small">
        Saves every item, its extracted text, and saved media to one zip file, with a manifest of
        checksums. Search vectors are not included; they are rebuilt on restore.
      </p>
      <button type="button" onClick={() => void runExport()} disabled={exporting}>
        {exporting ? "Exporting…" : "Export to zip…"}
      </button>
      {exported?.path && (
        <Notice tone="success" title="Export saved">
          {exported.item_count} items, {exported.chunk_count} passages, {exported.media_count} media
          files ({formatBytes(exported.bytes ?? 0)}) saved to{" "}
          <span className="path">{exported.path}</span>. The file is not encrypted.
        </Notice>
      )}
      <h3>Retention</h3>
      <p className="muted small">
        Applies to images OmniRecall stores itself, such as screenshots once screenshot capture is
        available. Text stays searchable after its image is removed. Text items are kept until you
        delete them.
      </p>
      {usage && (
        <p className="small">
          Saved media: {formatBytes(usage.media_bytes)} of {formatBytes(usage.media_cap_bytes)}
        </p>
      )}
      <form
        className="limits"
        onSubmit={(event) => {
          event.preventDefault();
          void save();
        }}
      >
        <div className="field">
          <label htmlFor="retention-days">Keep screenshot images for (days)</label>
          <input
            id="retention-days"
            type="number"
            min={0}
            max={3650}
            required
            value={days}
            onChange={(event) => setDays(event.target.value)}
          />
        </div>
        <div className="field">
          <label htmlFor="media-cap">Media storage limit (GB)</label>
          <input
            id="media-cap"
            type="number"
            min={0}
            step={0.5}
            required
            value={capGb}
            onChange={(event) => setCapGb(event.target.value)}
          />
        </div>
        <div className="row-actions">
          <button type="submit">Save retention</button>
        </div>
      </form>
      {message && <Notice tone={message.tone}>{message.text}</Notice>}
    </section>
  );
}
