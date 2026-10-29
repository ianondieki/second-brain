import { cn } from "./cn";

/**
 * A 2 px single-series line with a marker on the last point, for a stat tile (docs/platform/design/p18-design-system.md,
 * data viz): decorative, the tile's value and meta carry the meaning. Empty or one-point series draw nothing.
 */
export function Sparkline({ values, className }: { values: readonly number[]; className?: string }) {
  if (values.length < 2) return null;
  const w = 96;
  const h = 28;
  const pad = 3;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const step = (w - pad * 2) / (values.length - 1);
  const points = values.map((v, i) => [pad + i * step, pad + (h - pad * 2) * (1 - (v - min) / span)] as const);
  const d = points.map(([x, y], i) => `${i === 0 ? "M" : "L"}${x.toFixed(1)} ${y.toFixed(1)}`).join(" ");
  const [lx, ly] = points[points.length - 1];
  return (
    <svg aria-hidden="true" focusable="false" viewBox={`0 0 ${w} ${h}`} width={w} height={h} className={cn("block overflow-visible", className)} data-sparkline="">
      <path d={d} fill="none" stroke="var(--accent)" strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" />
      <circle cx={lx} cy={ly} r="3" fill="var(--accent)" stroke="var(--field)" strokeWidth="2" />
    </svg>
  );
}
