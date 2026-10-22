import { Clipboard, FileText, Image, Mic, Monitor, Type, type LucideIcon } from "lucide-react";

const icons: Record<string, LucideIcon> = {
  file: FileText,
  audio: Mic,
  screenshot: Monitor,
  image: Image,
  clipboard: Clipboard,
  text: Type,
};

/** The kind shown for an item: imported audio files read as audio, not files. */
export function sourceKind(sourceType: string, format?: unknown): string {
  if (format === "audio") return "audio";
  if (format === "image" && sourceType === "file") return "image";
  return sourceType;
}

/** A small gradient tile with the source's icon, as in the launch video. Decorative. */
export function SourceTile({ kind, size = "md" }: { kind: string; size?: "sm" | "md" | "lg" }) {
  const Icon = icons[kind] ?? FileText;
  const px = size === "sm" ? 15 : size === "lg" ? 26 : 18;
  return (
    <span className={`tile tile-${kind} ${size === "md" ? "" : size}`} aria-hidden="true">
      <Icon size={px} strokeWidth={2.2} />
    </span>
  );
}
