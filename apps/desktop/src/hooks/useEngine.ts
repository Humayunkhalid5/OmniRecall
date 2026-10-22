import { useCallback, useEffect, useRef, useState } from "react";
import {
  engine,
  onEngineNotification,
  onEngineState,
  type EngineNotification,
} from "../api/engine";
import type { EngineState, EngineStatus, RecoveryStatus } from "../api/types";

/** Engine lifecycle state pushed by the Rust supervisor. */
export function useEngineState(): EngineState {
  const [state, setState] = useState<EngineState>({ state: "starting" });
  useEffect(() => {
    let active = true;
    engine
      .state()
      .then((s) => active && setState(s))
      .catch(() => active && setState({ state: "failed", code: "shell_unavailable" }));
    const unlisten = onEngineState((s) => active && setState(s));
    return () => {
      active = false;
      void unlisten.then((off) => off());
    };
  }, []);
  return state;
}

/** Subscribe to engine notifications for the component's lifetime. */
export function useEngineEvents(handler: (note: EngineNotification) => void): void {
  const ref = useRef(handler);
  useEffect(() => {
    ref.current = handler;
  }, [handler]);
  useEffect(() => {
    const unlisten = onEngineNotification((note) => ref.current(note));
    return () => {
      void unlisten.then((off) => off());
    };
  }, []);
}

/**
 * Polls `status` while the engine runs; faster while work is queued. An engine
 * that found its database damaged reports `recovery` instead (D-036).
 */
export function useStatus(running: boolean): {
  status: EngineStatus | null;
  recovery: RecoveryStatus | null;
  refresh: () => void;
} {
  const [status, setStatus] = useState<EngineStatus | null>(null);
  const [recovery, setRecovery] = useState<RecoveryStatus | null>(null);
  const [tick, setTick] = useState(0);
  const refresh = useCallback(() => setTick((t) => t + 1), []);
  useEffect(() => {
    if (!running) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const load = async () => {
      try {
        const next = await engine.status();
        if (cancelled) return;
        if (next.engine === "recovery") {
          setRecovery(next as unknown as RecoveryStatus);
          setStatus(null);
          timer = setTimeout(load, 5000);
          return;
        }
        setRecovery(null);
        setStatus(next);
        const busy = next.queue.active > 0 || next.index.pending_vector_writes > 0;
        timer = setTimeout(load, busy ? 1000 : 5000);
      } catch {
        if (!cancelled) timer = setTimeout(load, 3000);
      }
    };
    void load();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [running, tick]);
  return { status, recovery, refresh };
}
