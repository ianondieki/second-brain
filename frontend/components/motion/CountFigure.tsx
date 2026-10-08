import type { CSSProperties } from "react";

/**
 * A whole number that counts up once inside a CountUp box (globals.css `.count`): the drawn figure is decorative and
 * the real one is read by assistive technology (and by anyone whose script never runs: the figure then stands as it
 * is). Anything that is not a non-negative integer is set as it is, without counting.
 */
export function CountFigure({ value }: { value: number | string }) {
  if (typeof value !== "number" || !Number.isInteger(value) || value < 0) return <>{value}</>;
  return (
    <>
      <span aria-hidden="true" className="count" style={{ "--to": value } as CSSProperties} data-count={value} />
      <span className="sr-only">{value}</span>
    </>
  );
}
