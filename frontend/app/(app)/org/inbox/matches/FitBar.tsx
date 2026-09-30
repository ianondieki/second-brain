/**
 * A match's fit, 0 to 100, drawn: a short bar and the number (the bar is decoration; the words carry the meaning, and
 * a screen reader hears the long form, "Fit 82 out of 100"). No i18n or router import: the words come in formatted,
 * so the scout Preview (a client component) and FitMeter (the server's) share it. `data-chip` counts it as one of a
 * row's at most two chips.
 */
export function FitBar({ value, short, long }: { value: number; short: string; long: string }) {
  const width = Math.max(0, Math.min(100, Math.round(value)));
  return (
    <span data-chip="fit" className="inline-flex items-center gap-2 text-sm font-semibold text-jacaranda">
      {/* Square ends: rounded-full is kept for the avatar and the one solid badge (the design plan's Radius). */}
      <span aria-hidden="true" className="relative h-1.5 w-14 overflow-hidden bg-line">
        <span className="absolute inset-y-0 left-0 bg-jacaranda" style={{ width: `${width}%` }} />
      </span>
      <span aria-hidden="true" className="tabular-nums">
        {short}
      </span>
      <span className="sr-only">{long}</span>
    </span>
  );
}
