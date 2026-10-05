/** The star: an outline when off, filled in the accent when on (decorative; the name and aria-pressed say it). */
export function StarIcon({ on, className }: { on: boolean; className?: string }) {
  return (
    <svg aria-hidden="true" focusable="false" viewBox="0 0 20 20" className={className}>
      <path
        d="M10 2.4l2.35 4.77 5.26.76-3.8 3.71.9 5.24L10 14.4l-4.71 2.48.9-5.24-3.8-3.7 5.26-.77z"
        fill={on ? "currentColor" : "none"}
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinejoin="round"
      />
    </svg>
  );
}
