import { useState } from "react";
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
      <h1>Welcome to OmniRecall</h1>
      <p className="lead">
        OmniRecall lets you search what you have saved, copied, or imported, in your own words. It
        runs entirely on this computer.
      </p>
      <section aria-labelledby="captured-heading">
        <h2 id="captured-heading">What it captures</h2>
        <ul>
          <li>
            <strong>Nothing, until you turn a source on.</strong> Clipboard capture is off. You can
            switch it on in Settings and pause it at any time.
          </li>
          <li>Files, folders, and text you import yourself.</li>
          <li>
            When clipboard capture is on: text you copy. Copies that look like passwords, keys, or
            card numbers are dropped on a best-effort basis. That filter cannot catch everything, so
            pause capture or exclude an app before copying something sensitive.
          </li>
        </ul>
      </section>
      <section aria-labelledby="not-heading">
        <h2 id="not-heading">What it does not do</h2>
        <ul>
          <li>It sends nothing you capture, import, or search to the internet.</li>
          <li>It has no account, analytics, or telemetry.</li>
          <li>It only goes online if you choose to download a search model.</li>
        </ul>
      </section>
      <section aria-labelledby="control-heading">
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
      {error && <Notice tone="error">{error}</Notice>}
      <button type="button" className="primary" onClick={() => void finish()} disabled={busy}>
        {busy ? "Starting…" : "Continue with capture off"}
      </button>
    </main>
  );
}
