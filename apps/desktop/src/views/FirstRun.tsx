import { ArrowRight, EyeOff, ShieldCheck, SlidersHorizontal } from "lucide-react";
import { useState } from "react";
import { BrandMark } from "../components/BrandMark";
import { engine, EngineCallError } from "../api/engine";
import { Notice } from "../components/Notice";

interface Props {
  onDone: () => void;
}

/** First launch: what is and is not captured, with every source off (design §8). */
export function FirstRun({ onDone }: Props) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const finish = async () => {
    setBusy(true);
    try {
      await engine.updateSettings({ first_run_completed: true });
      onDone();
    } catch (e) {
      setError((e as EngineCallError).message);
      setBusy(false);
    }
  };

  return (
    <main className="first-run">
      <div className="hero">
        <BrandMark size={56} />
        <p className="eyebrow">Private by design</p>
        <h1>
          Welcome to <span className="gradient-text">OmniRecall</span>
        </h1>
        <p className="lead">
          OmniRecall lets you search what you have saved, copied, or imported, in your own words. It
          runs entirely on this computer.
        </p>
      </div>
      <div className="cards">
        <section className="card" aria-labelledby="captured-heading">
          <span className="tile" aria-hidden="true">
            <EyeOff size={18} strokeWidth={2.2} />
          </span>
          <h2 id="captured-heading">What it captures</h2>
          <ul>
            <li>
              <strong>Nothing, until you turn a source on.</strong> Clipboard and screenshot capture
              are off. You can switch each one on in Settings and pause it at any time.
            </li>
            <li>Files, folders, and text you import yourself.</li>
            <li>
              When clipboard capture is on: text you copy. Copies that look like passwords, keys, or
              card numbers are dropped on a best-effort basis. That filter cannot catch everything,
              so pause capture or exclude an app before copying something sensitive.
            </li>
            <li>
              When screenshot capture is on: a picture of each screen at the interval you choose,
              with its text read on this computer. It skips frames while the screen is locked, while
              you are away, while OmniRecall or an excluded app is in front, and when nothing has
              changed. Images are kept for 7 days by default, then only their text.
            </li>
          </ul>
        </section>
        <section className="card" aria-labelledby="not-heading">
          <span className="tile tile-audio" aria-hidden="true">
            <ShieldCheck size={18} strokeWidth={2.2} />
          </span>
          <h2 id="not-heading">What it does not do</h2>
          <ul>
            <li>It sends nothing you capture, import, or search to the internet.</li>
            <li>It has no account, analytics, or telemetry.</li>
            <li>It only goes online if you choose to download a search model.</li>
          </ul>
        </section>
        <section className="card" aria-labelledby="control-heading">
          <span className="tile tile-clipboard" aria-hidden="true">
            <SlidersHorizontal size={18} strokeWidth={2.2} />
          </span>
          <h2 id="control-heading">You stay in control</h2>
          <ul>
            <li>
              The capture status is always shown in the window, and in the system tray where your
              desktop has one.
            </li>
            <li>Delete any item, or everything, and it is removed from disk.</li>
            <li>Export your data to a zip file whenever you like.</li>
            <li>
              Your index is not encrypted by OmniRecall. Turn on your system&apos;s disk encryption
              (BitLocker, FileVault, or LUKS) to protect it.
            </li>
          </ul>
        </section>
      </div>
      {error && <Notice tone="error">{error}</Notice>}
      <div className="first-run-actions">
        <button type="button" className="primary" onClick={() => void finish()} disabled={busy}>
          {busy ? "Starting…" : "Continue with capture off"}
          <ArrowRight size={18} aria-hidden="true" />
        </button>
        <span className="muted small">You can turn sources on later in Settings.</span>
      </div>
    </main>
  );
}
