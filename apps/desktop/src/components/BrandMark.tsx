import { useId } from "react";

/** The OmniRecall mark: a magnifier on an ember-to-rose tile. Decorative. */
export function BrandMark({ size = 34 }: { size?: number }) {
  const gradient = useId();
  return (
    <svg
      className="brand-mark"
      width={size}
      height={size}
      viewBox="0 0 40 40"
      aria-hidden="true"
      focusable="false"
    >
      <defs>
        <linearGradient id={gradient} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#ff9a4d" />
          <stop offset="0.45" stopColor="#ff6a3d" />
          <stop offset="1" stopColor="#ff2e7e" />
        </linearGradient>
      </defs>
      <rect width="40" height="40" rx="11" fill={`url(#${gradient})`} />
      <circle cx="17.5" cy="17.5" r="7.5" fill="none" stroke="#fff" strokeWidth="3.2" />
      <path d="M23.2 23.2 29.5 29.5" stroke="#fff" strokeWidth="3.6" strokeLinecap="round" />
      <circle cx="17.5" cy="17.5" r="2.2" fill="#fff" opacity="0.9" />
    </svg>
  );
}
