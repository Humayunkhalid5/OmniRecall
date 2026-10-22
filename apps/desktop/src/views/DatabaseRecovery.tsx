import { useState } from "react";
import { engine, EngineCallError } from "../api/engine";
import type { RecoveryReport, RecoveryStatus } from "../api/types";
import { BrandMark } from "../components/BrandMark";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { Notice } from "../components/Notice";
import { formatBytes } from "../lib/format";

type Outcome = { action: "recovered"; report: RecoveryReport } | { action: "reset" };

const reasonText: Record<
  Exclude<RecoveryStatus["database"]["reason"], "schema_too_new">,
  string
> = {
  malformed:
    "Part of the database file could not be read. This can happen after a disk error, or if the computer lost power while OmniRecall was saving.",
  not_a_database: "The database file could not be read at all, so nothing in it can be recovered.",
};

/**
 * Shown when the engine started in recovery mode because its database is
 * damaged (D-036). Nothing changes until the user picks an action.
 */
export function DatabaseRecovery({ recovery }: { recovery: RecoveryStatus }) {
  const { database } = recovery;
  const [confirm, setConfirm] = useState<"recover" | "reset" | null>(null);
  const [busy, setBusy] = useState(false);
  const [outcome, setOutcome] = useState<Outcome | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [restarting, setRestarting] = useState(false);
  const canRecover = database.reason === "malformed";

  const run = async (action: "recover" | "reset") => {
    setBusy(true);
    setError(null);
    try {
      if (action === "recover") {
        setOutcome({ action: "recovered", report: await engine.recoverDatabase() });
      } else {
        await engine.resetDatabase();
        setOutcome({ action: "reset" });
      }
    } catch (e) {
      setError(e instanceof EngineCallError ? e.message : "The action could not be completed.");
    } finally {
      setBusy(false);
      setConfirm(null);
    }
  };

  const restart = () => {
    setRestarting(true);
    // A failed restart is reported through the next engine state.
    engine
      .restart()
      .catch(() => undefined)
      .finally(() => setRestarting(false));
  };

  const brand = (
    <div className="center-brand">
      <BrandMark size={44} />
      <h1>OmniRecall</h1>
    </div>
  );

  const restartButton = (
    <button type="button" className="primary" disabled={restarting} onClick={restart}>
      {restarting ? "Restarting…" : "Restart OmniRecall"}
    </button>
  );

  if (database.reason === "schema_too_new") {
    return (
      <main className="center recovery">
        {brand}
        <Notice tone="warning" title="Your data was saved by a newer version of OmniRecall">
          <p>
            This version cannot open it. Install the newer version again to get back to your data.
            Nothing has been changed.
          </p>
          <p className="muted small">{database.path}</p>
        </Notice>
      </main>
    );
  }

  if (outcome || database.state === "restart_needed") {
    return (
      <main className="center recovery">
        {brand}
        {outcome?.action === "recovered" ? (
          <RecoveredSummary report={outcome.report} />
        ) : (
          <Notice tone="success" title="Done">
            <p>
              {outcome?.action === "reset"
                ? "Your saved items, the search index, and stored screenshots and recordings were deleted. OmniRecall will start empty."
                : "The database was repaired."}
            </p>
          </Notice>
        )}
        <p>Restart OmniRecall to finish.</p>
        {restartButton}
      </main>
    );
  }

  return (
    <main className="center recovery">
      {brand}
      <Notice tone="error" title="Your OmniRecall database is damaged">
        <p>{reasonText[database.reason]}</p>
        <p className="muted small">
          {database.path} ({formatBytes(database.bytes)})
        </p>
        <p>
          Nothing has been changed yet. OmniRecall will not open a damaged database, so choose what
          to do.
        </p>
      </Notice>
      {error && (
        <Notice tone="error" title="That did not work">
          {error}
        </Notice>
      )}
      <ul className="recovery-options">
        {canRecover && (
          <li>
            <h2>Recover what can be read</h2>
            <p>
              Copies every readable item, setting and exclusion into a new database and replaces the
              damaged file. Items in the damaged part are listed so you can see what was lost.
              Capture is turned off afterwards so you can check your exclusions first.
            </p>
            <button type="button" className="primary" onClick={() => setConfirm("recover")}>
              Recover what can be read
            </button>
          </li>
        )}
        <li>
          <h2>Start over</h2>
          <p>
            Permanently deletes everything OmniRecall saved: items, settings, exclusions, the search
            index, and stored screenshots and recordings. Files you imported stay where they are.
          </p>
          <button type="button" className="danger" onClick={() => setConfirm("reset")}>
            Start over
          </button>
        </li>
      </ul>
      <p className="muted small">
        If you have a backup of the database file, quit OmniRecall and put it back at the path above
        instead.
      </p>
      <ConfirmDialog
        open={confirm === "recover"}
        title="Recover the database?"
        body={
          <p>
            The damaged file is replaced by the recovered copy. Anything that could not be read is
            gone for good.
          </p>
        }
        confirmLabel="Recover"
        busy={busy}
        onConfirm={() => void run("recover")}
        onCancel={() => setConfirm(null)}
      />
      <ConfirmDialog
        open={confirm === "reset"}
        title="Delete everything and start over?"
        body={<p>This permanently deletes everything OmniRecall saved. It cannot be undone.</p>}
        confirmLabel="Delete everything"
        destructive
        busy={busy}
        onConfirm={() => void run("reset")}
        onCancel={() => setConfirm(null)}
      />
    </main>
  );
}

function RecoveredSummary({ report }: { report: RecoveryReport }) {
  const items = report.copied.items ?? 0;
  return (
    <Notice tone={report.complete ? "success" : "warning"} title="Recovery finished">
      <p>
        {items === 1 ? "1 item was recovered." : `${items} items were recovered.`}{" "}
        {report.complete
          ? "Every part of the database could be read."
          : "Some parts could not be read."}
      </p>
      <ul>
        {report.lost > 0 && (
          <li>
            {report.lost === 1 ? "1 item" : `${report.lost} items`} lost their text. They are listed
            as failed in the Library.
          </li>
        )}
        {report.requeued > 0 && (
          <li>
            {report.requeued === 1 ? "1 imported file" : `${report.requeued} imported files`} will
            be read again from disk.
          </li>
        )}
        {report.media_removed > 0 && (
          <li>
            {report.media_removed === 1
              ? "1 stored screenshot or recording"
              : `${report.media_removed} stored screenshots or recordings`}{" "}
            no longer belonged to any item and were deleted.
          </li>
        )}
        <li>Capture is off. Check your exclusions in Settings before you turn it back on.</li>
      </ul>
    </Notice>
  );
}
