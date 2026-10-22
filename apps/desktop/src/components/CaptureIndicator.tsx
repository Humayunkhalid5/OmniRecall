import { Pause, Play, Power } from "lucide-react";
import type { CaptureState } from "../api/types";

interface Props {
  capture: CaptureState | null;
  onToggle: () => void;
  onOpenSettings: () => void;
}

/** Always-visible capture status with one-action pause (design §8). */
export function CaptureIndicator({ capture, onToggle, onOpenSettings }: Props) {
  if (!capture) return null;
  const enabled = Object.values(capture.sources).some((s) => s.enabled);
  if (!enabled) {
    return (
      <button type="button" className="capture-chip capture-off" onClick={onOpenSettings}>
        <Power size={15} aria-hidden="true" />
        Capture off
      </button>
    );
  }
  const active = capture.capturing;
  const sources = Object.entries(capture.sources)
    .filter(([, s]) => s.active)
    .map(([name]) => (name === "clipboard" ? "clipboard" : "screenshots"));
  const label = sources.length ? `Capturing ${sources.join(" and ")}` : "Capturing";
  return (
    <div className={`capture-chip ${active ? "capture-on" : "capture-paused"}`} role="status">
      <span className="capture-line">
        <span className={`dot ${active ? "dot-live" : "dot-busy"}`} aria-hidden="true" />
        <span>{active ? label : "Capture paused"}</span>
      </span>
      <button type="button" className={active ? "" : "primary"} onClick={onToggle}>
        {active ? <Pause size={15} aria-hidden="true" /> : <Play size={15} aria-hidden="true" />}
        {active ? "Pause" : "Resume"}
      </button>
    </div>
  );
}
