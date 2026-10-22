/**
 * Renders text with highlight ranges as <mark>; never injects HTML.
 *
 * The engine counts offsets in Unicode code points (Python string indices),
 * while JavaScript strings index UTF-16 units, so text is split into code
 * points first. Otherwise every emoji or other astral character before a match
 * would shift the highlight. Ranges are sorted, clamped, and merged, so a bad
 * range can never duplicate or drop text.
 */
export function Highlighted({ text, ranges }: { text: string; ranges: [number, number][] }) {
  const points = Array.from(text);
  const spans = ranges
    .map(([start, end]) => [Math.max(0, start), Math.min(points.length, end)] as const)
    .filter(([start, end]) => end > start)
    .sort((a, b) => a[0] - b[0]);
  const parts: React.ReactNode[] = [];
  let cursor = 0;
  spans.forEach(([start, end], index) => {
    if (end <= cursor) return;
    const from = Math.max(start, cursor);
    if (from > cursor) parts.push(points.slice(cursor, from).join(""));
    parts.push(<mark key={index}>{points.slice(from, end).join("")}</mark>);
    cursor = end;
  });
  if (cursor < points.length) parts.push(points.slice(cursor).join(""));
  return <>{parts}</>;
}
