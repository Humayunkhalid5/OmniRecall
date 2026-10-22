const units = ["B", "KB", "MB", "GB", "TB"];

export function formatBytes(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes <= 0) return "0 B";
  const exponent = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  const value = bytes / 1024 ** exponent;
  return `${value >= 10 || exponent === 0 ? value.toFixed(0) : value.toFixed(1)} ${units[exponent]}`;
}

/** Stored timestamps are UTC; render them in the user's local time zone (rules §4.2). */
export function formatLocalTime(iso: string, now: Date = new Date()): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "Unknown time";
  const sameDay = date.toDateString() === now.toDateString();
  const options: Intl.DateTimeFormatOptions = sameDay
    ? { hour: "numeric", minute: "2-digit" }
    : { year: "numeric", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" };
  const text = new Intl.DateTimeFormat(undefined, options).format(date);
  return sameDay ? `Today, ${text}` : text;
}

export const sourceLabels: Record<string, string> = {
  text: "Pasted text",
  clipboard: "Clipboard",
  file: "File",
  screenshot: "Screenshot",
  image: "Image",
  audio: "Audio",
};

export const statusLabels: Record<string, string> = {
  queued: "Queued",
  processing: "Processing",
  indexed: "Indexed",
  failed: "Failed",
  skipped: "Skipped",
  deleting: "Deleting…",
  deleted: "Deleted",
};

const errorMessages: Record<string, string> = {
  source_missing: "The original file was moved or deleted.",
  unsupported_format: "This file type is not supported.",
  limit_exceeded: "The file is over a configured limit (size, pages, or recording length).",
  extraction_empty: "No readable text was found.",
  malformed_file: "The file appears to be damaged.",
  encrypted_file: "Password-protected files are not supported.",
  binary_content: "The file does not contain readable text.",
  model_missing: "The search model is not installed yet.",
  cancelled: "Processing was cancelled.",
  payload_missing: "The captured content is no longer available.",
  ocr_unavailable: "Text recognition (Tesseract) is not installed.",
  ocr_failed: "Text recognition failed for this image.",
  ocr_timeout: "Text recognition took too long.",
  transcription_model_missing: "The speech model is not installed. Set it up in Settings → Models.",
  audio_decoder_unavailable: "The audio decoder is missing from this installation.",
  unsupported_codec: "This audio encoding is not supported (for example Opus).",
  recovery_lost_text:
    "Its text was in a damaged part of the database and could not be recovered. Delete it, or add it again.",
};

export function describeError(code: string | null | undefined): string {
  if (!code) return "Something went wrong.";
  return (
    errorMessages[code] ?? (code.startsWith("internal") ? "An internal error occurred." : code)
  );
}

/** A position in a recording, such as 4:05 or 1:02:07. */
export function formatClock(ms: number): string {
  const total = Math.max(0, Math.floor(ms / 1000));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const seconds = String(total % 60).padStart(2, "0");
  return hours > 0
    ? `${hours}:${String(minutes).padStart(2, "0")}:${seconds}`
    : `${minutes}:${seconds}`;
}

/** A recording length, such as "8 s", "4 min 5 s", or "1 h 2 min". */
export function formatDuration(seconds: number): string {
  const total = Math.round(seconds);
  if (total < 60) return `${total} s`;
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  if (hours > 0) return `${hours} h ${minutes} min`;
  const rest = total % 60;
  return rest ? `${minutes} min ${rest} s` : `${minutes} min`;
}

/** The language name for a Whisper language code, in the user's language. */
export function languageName(code: string): string {
  try {
    return new Intl.DisplayNames(undefined, { type: "language" }).of(code) ?? code;
  } catch {
    return code;
  }
}
