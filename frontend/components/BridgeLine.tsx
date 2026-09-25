// The one memorable element (docs/platform/design/phase1-auth-ui.md): a single jacaranda stroke from a Developer
// node to an Organisation node through four stage ticks, the tracker both sides will share. Pure SVG, no JS.

type Point = readonly [number, number];

const START: Point = [16, 96];
const CONTROL: Point = [160, -24];
const END: Point = [304, 96];
const TICK_HALF_LENGTH = 7;
const STAGES = [0.2, 0.4, 0.6, 0.8] as const;

const round = (n: number) => Math.round(n * 100) / 100;

/** A point and the unit normal on the quadratic curve START-CONTROL-END at parameter t. */
function pointAndNormal(t: number): { at: Point; normal: Point } {
  const u = 1 - t;
  const at: Point = [
    u * u * START[0] + 2 * u * t * CONTROL[0] + t * t * END[0],
    u * u * START[1] + 2 * u * t * CONTROL[1] + t * t * END[1],
  ];
  const dx = 2 * u * (CONTROL[0] - START[0]) + 2 * t * (END[0] - CONTROL[0]);
  const dy = 2 * u * (CONTROL[1] - START[1]) + 2 * t * (END[1] - CONTROL[1]);
  const length = Math.hypot(dx, dy);
  return { at, normal: [-dy / length, dx / length] };
}

const TICKS = STAGES.map((t) => {
  const { at, normal } = pointAndNormal(t);
  return {
    x1: round(at[0] - normal[0] * TICK_HALF_LENGTH),
    y1: round(at[1] - normal[1] * TICK_HALF_LENGTH),
    x2: round(at[0] + normal[0] * TICK_HALF_LENGTH),
    y2: round(at[1] + normal[1] * TICK_HALF_LENGTH),
  };
});

const ARCH = `M${START.join(" ")} Q${CONTROL.join(" ")} ${END.join(" ")}`;

export interface BridgeLineProps {
  developerLabel: string;
  organisationLabel: string;
  /** Draw the stroke once on load (landing page only); otherwise it is simply drawn. */
  animate?: boolean;
}

export function BridgeLine({ developerLabel, organisationLabel, animate = false }: BridgeLineProps) {
  return (
    <div aria-hidden="true" className="w-full max-w-80 select-none">
      <svg viewBox="0 0 320 112" className="block h-auto w-full overflow-visible" focusable="false">
        {TICKS.map((tick) => (
          <line
            key={`${tick.x1}-${tick.y1}`}
            {...tick}
            stroke="var(--jacaranda)"
            strokeOpacity="0.55"
            strokeWidth="2"
            strokeLinecap="round"
          />
        ))}
        <path
          d={ARCH}
          pathLength={100}
          fill="none"
          stroke="var(--jacaranda)"
          strokeWidth="3"
          strokeLinecap="round"
          className={animate ? "bridge-draw" : undefined}
        />
        <circle cx={START[0]} cy={START[1]} r="7" fill="var(--jacaranda)" />
        <circle cx={END[0]} cy={END[1]} r="6" fill="var(--jacaranda-wash)" stroke="var(--jacaranda)" strokeWidth="3" />
      </svg>
      <div className="mt-2 flex justify-between gap-4 text-sm font-medium text-ink-soft">
        <span>{developerLabel}</span>
        <span className="text-right">{organisationLabel}</span>
      </div>
    </div>
  );
}
