import { useCallback, useEffect, useState } from "react";
import { engine, EngineCallError } from "../api/engine";
import type {
  CaptureState,
  Exclusion,
  ExportResult,
  ScreenshotStatus,
  StorageUsage,
} from "../api/types";
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

const screenshotLabels: Record<string, string> = {
  captured: "captured",
  duplicate_image: "skipped as unchanged",
  same_text: "skipped as the same text",
  no_text: "skipped with no text",
  sensitive: "dropped as possibly sensitive",
  excluded_app: "skipped for excluded apps",
  excluded_pattern: "dropped by text exclusions",
  app_unknown: "skipped because the app could not be identified",
  own_app: "skipped while OmniRecall was in front",
  idle: "skipped while you were away",
  locked: "skipped while the screen was locked",
  permission_needed: "skipped without screen permission",
  capture_failed: "failed to capture",
  ocr_unavailable: "skipped without text recognition",
  queue_full: "skipped because indexing was busy",
  too_large: "dropped as too large",
};

function countSummary(counts: Record<string, number>, labels: Record<string, string>): string {
  return Object.entries(counts)
    .filter(([, n]) => n > 0)
    .map(([outcome, n]) => `${n} ${labels[outcome] ?? outcome}`)
    .join(", ");
}

const unsupportedText: Record<string, string> = {
  wayland:
    "Screenshot capture is not available on Wayland: the system asks for permission on every capture, so periodic capture cannot work. Log in with an X11 session to use it.",
  no_display: "No display was found, so screenshots cannot be taken.",
};

interface ScreenshotProps {
  capture: CaptureState;
  setSource: CaptureControls["setSource"];
}

function ScreenshotSection({ capture, setSource }: ScreenshotProps) {
  const source = capture.sources.screenshot;
  const [status, setStatus] = useState<ScreenshotStatus | null>(null);
  const [interval, setIntervalText] = useState(String(capture.screenshot?.interval_s ?? 30));
  const [idleMin, setIdleMin] = useState(
    String(Math.round((capture.screenshot?.pause_on_idle_s ?? 300) / 60)),
  );
  const [message, setMessage] = useState<{ tone: "success" | "error"; text: string } | null>(null);

  const loadStatus = useCallback(
    () =>
      engine
        .screenshotStatus()
        .then(setStatus)
        .catch(() => setStatus(null)),
    [],
  );

  useEffect(() => {
    void loadStatus();
    const timer = setInterval(() => void loadStatus(), COUNTS_REFRESH_MS);
    return () => clearInterval(timer);
  }, [loadStatus]);

  const ocrMissing = capture.ocr ? !capture.ocr.available : false;
  const unsupported = status?.unsupported_reason ?? null;
  const blocked = Boolean(unsupported) || ocrMissing;
  const needsPermission = status?.permission === "denied";
  const counts = countSummary(capture.session?.screenshot ?? {}, screenshotLabels);

  const saveTiming = async () => {
    try {
      await engine.updateSettings({
        screenshot_interval_s: Number(interval),
        pause_on_idle_s: Math.round(Number(idleMin) * 60),
      });
      setMessage({ tone: "success", text: "Saved." });
    } catch (e) {
      setMessage({ tone: "error", text: (e as EngineCallError).message });
    }
  };

  const askPermission = async () => {
    const granted = await engine.requestScreenPermission().catch(() => false);
    await loadStatus();
    if (!granted) {
      setMessage({
        tone: "error",
        text: "Screen recording is still off. Allow OmniRecall in System Settings → Privacy & Security → Screen Recording, then restart OmniRecall.",
      });
    }
  };

  const openSettings = async () => {
    try {
      await engine.openScreenPermissionSettings();
    } catch (e) {
      setMessage({ tone: "error", text: (e as EngineCallError).message });
    }
  };

  return (
    <>
      <div className="switch-row">
        <div>
          <label htmlFor="screenshot-enabled" className="switch-label">
            Screenshots
          </label>
          <p className="muted small" id="screenshot-help">
            Takes a picture of each screen every {capture.screenshot?.interval_s ?? 30} seconds and
            reads its text on this computer, so you can search what was on screen. Frames are
            skipped while the screen is locked, while you are away, while OmniRecall or an excluded
            app is in front, and when the screen has not changed.
          </p>
        </div>
        <input
          id="screenshot-enabled"
          type="checkbox"
          role="switch"
          aria-describedby="screenshot-help"
          checked={source.enabled}
          disabled={blocked && !source.enabled}
          onChange={(event) => void setSource("screenshot", { enabled: event.target.checked })}
        />
      </div>
      {unsupported && <Notice tone="info">{unsupportedText[unsupported] ?? unsupported}</Notice>}
      {ocrMissing && (
        <Notice tone="info">
          Text recognition (Tesseract) is not installed, so screenshots cannot be read. Install
          Tesseract and restart OmniRecall.
        </Notice>
      )}
      {needsPermission && (
        <Notice tone="error" title="Screen recording permission needed">
          macOS has not allowed OmniRecall to record the screen, so no screenshots are taken.
          <div className="row-actions">
            <button type="button" onClick={() => void askPermission()}>
              Ask for permission
            </button>
            <button type="button" onClick={() => void openSettings()}>
              Open System Settings
            </button>
          </div>
        </Notice>
      )}
      {source.enabled && (
        <>
          <div className="switch-row nested">
            <label htmlFor="screenshot-paused" className="switch-label">
              Pause screenshots only
            </label>
            <input
              id="screenshot-paused"
              type="checkbox"
              role="switch"
              checked={source.paused}
              onChange={(event) => void setSource("screenshot", { paused: event.target.checked })}
            />
          </div>
          <form
            className="limits nested"
            onSubmit={(event) => {
              event.preventDefault();
              void saveTiming();
            }}
          >
            <div className="field">
              <label htmlFor="screenshot-interval">Seconds between screenshots</label>
              <input
                id="screenshot-interval"
                type="number"
                min={5}
                max={3600}
                required
                value={interval}
                onChange={(event) => setIntervalText(event.target.value)}
              />
            </div>
            <div className="field">
              <label htmlFor="idle-pause">Pause after inactivity (minutes, 0 = never)</label>
              <input
                id="idle-pause"
                type="number"
                min={0}
                max={1440}
                required
                value={idleMin}
                onChange={(event) => setIdleMin(event.target.value)}
              />
            </div>
            <div className="row-actions">
              <button type="submit">Save timing</button>
            </div>
          </form>
        </>
      )}
      {message && <Notice tone={message.tone}>{message.text}</Notice>}
      {source.enabled && counts && (
        <p className="muted small" aria-live="polite">
          Screenshots since the app started: {counts}.
        </p>
      )}
    </>
  );
}

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
      .then((r) =>
        setDetectSecrets(
          Boolean(r.settings.clipboard_detect_secrets) &&
            Boolean(r.settings.screenshot_detect_secrets),
        ),
      )
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
  const countText = countSummary(capture.session?.clipboard ?? {}, outcomeLabels);

  const toggleSecrets = async (value: boolean) => {
    try {
      await engine.updateSettings({
        clipboard_detect_secrets: value,
        screenshot_detect_secrets: value,
      });
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
      {clipboard.enabled && countText && (
        <p className="muted small" aria-live="polite">
          Clipboard since the app started: {countText}.
        </p>
      )}
      <ScreenshotSection capture={capture} setSource={setSource} />
      <div className="switch-row">
        <div>
          <label htmlFor="secrets" className="switch-label">
            Drop captures that look like secrets
          </label>
          <p className="muted small" id="secrets-help">
            Best effort: recognises private keys, common API tokens, card numbers, and password-like
            text in copies and in the text read from screenshots. It cannot recognise every secret,
            and text in an image is only checked after the screenshot is taken.
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
        Checked before anything is saved. <strong>App</strong>: while that app is in front, copies
        are dropped and no screenshot is taken; if the app cannot be identified (for example on some
        Linux desktops), copies and screenshots are skipped whenever app exclusions exist.{" "}
        <strong>Text</strong>: copies, and screenshots whose text contains it, are dropped (exact
        text, not case-sensitive). <strong>Folder</strong>: files in that folder are never imported.
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
  const [textOnly, setTextOnly] = useState(false);
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
          setTextOnly(u.text_only_mode);
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
        text_only_mode: textOnly,
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
        Applies to images OmniRecall stores itself: screenshots. Text stays searchable after its
        image is removed. Text items and imported files are kept until you delete them.
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
        <div className="switch-row">
          <div>
            <label htmlFor="text-only" className="switch-label">
              Text only
            </label>
            <p className="muted small" id="text-only-help">
              Keep only the text read from new screenshots and remove each image as soon as it is
              indexed.
            </p>
          </div>
          <input
            id="text-only"
            type="checkbox"
            role="switch"
            aria-describedby="text-only-help"
            checked={textOnly}
            onChange={(event) => setTextOnly(event.target.checked)}
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
