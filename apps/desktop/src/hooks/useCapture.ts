import { useCallback, useEffect, useState } from "react";
import { engine, EngineCallError, type EngineNotification } from "../api/engine";
import type { CaptureState } from "../api/types";
import { useEngineEvents } from "./useEngine";

export interface CaptureControls {
  capture: CaptureState | null;
  error: string | null;
  setPaused: (paused: boolean) => Promise<void>;
  setSource: (
    source: "clipboard" | "screenshot",
    change: { enabled?: boolean; paused?: boolean },
  ) => Promise<void>;
  /** Pause everything when capturing; otherwise resume global and per-source pauses. */
  toggle: () => Promise<void>;
  refresh: () => void;
}

/** Capture state from the engine, kept current by its `capture.state` notifications. */
export function useCapture(running: boolean): CaptureControls {
  const [capture, setCapture] = useState<CaptureState | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(() => {
    engine
      .captureState()
      .then((state) => {
        setCapture(state);
        setError(null);
      })
      .catch((e: EngineCallError) => setError(e.message));
  }, []);

  useEffect(() => {
    if (running) refresh();
  }, [running, refresh]);

  useEngineEvents(
    useCallback((note: EngineNotification) => {
      if (note.method === "capture.state") {
        setCapture((prev) => ({
          ...(note.params as unknown as CaptureState),
          session: prev?.session,
        }));
      }
    }, []),
  );

  const apply = useCallback(async (request: Promise<CaptureState>) => {
    try {
      setCapture(await request);
      setError(null);
    } catch (e) {
      setError((e as EngineCallError).message);
    }
  }, []);

  const setPaused = useCallback((paused: boolean) => apply(engine.pauseCapture(paused)), [apply]);
  const setSource = useCallback(
    (source: "clipboard" | "screenshot", change: { enabled?: boolean; paused?: boolean }) =>
      apply(engine.setSource(source, change)),
    [apply],
  );

  const toggle = useCallback(async () => {
    if (!capture) return;
    if (capture.capturing) {
      await setPaused(true);
      return;
    }
    if (capture.paused) await setPaused(false);
    for (const [name, source] of Object.entries(capture.sources)) {
      if (source.enabled && source.paused) {
        await setSource(name as "clipboard" | "screenshot", { paused: false });
      }
    }
  }, [capture, setPaused, setSource]);

  return { capture, error, setPaused, setSource, toggle, refresh };
}
