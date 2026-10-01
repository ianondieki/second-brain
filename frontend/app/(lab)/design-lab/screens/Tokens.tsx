import { Badge } from "@/components/ui/Badge";
import { buttonClass } from "@/components/ui/Button";
import { StandaloneLink } from "@/components/ui/StandaloneLink";
import { Callout } from "@/components/ui/Callout";
import { AlertIcon, CheckIcon, ClockIcon, InfoIcon, LockIcon, SendIcon } from "@/components/ui/status-icons";
import { CompaniesIcon, HomeIcon, IdeasIcon } from "@/components/ui/icons";
import { DiscoverIcon } from "@/components/discover-icons";
import { EngagementsIcon } from "@/components/tracker/icons";
import { ChipMark } from "@/components/tracker/Chip";
import { EmptyStateFrame } from "@/components/ui/EmptyStateFrame";
import { Panel } from "@/components/ui/Panel";

import { Wordmark } from "../brand/Logo";
import { DIRECTION, type DirectionKey, type Theme } from "../directions";
import { PLACEHOLDER_NAME } from "../fixtures";
import { EmptyIllustration } from "./Illustration";

/** Every token of one direction on one page: palette, type, radius, elevation, icons, illustration, motion. */
export function TokensScreen({ direction, theme }: { direction: DirectionKey; theme: Theme }) {
  const d = DIRECTION[direction];
  const p = d[theme];
  const swatches: [string, string, string][] = [
    ["Paper", p.paper, "page"],
    ["Field", p.field, "inputs, cards"],
    ["Ink", p.ink, "text"],
    ["Ink soft", p.inkSoft, "secondary text"],
    ["Line", p.line, "hairlines"],
    ["Accent", p.accent, "act here"],
    ["Accent wash", p.accentWash, "selected, info"],
    ["Flourish", p.flourish, "seal, lattice, art"],
    ["Ok", p.ok, "success"],
    ["Error", p.error, "errors"],
  ];
  return (
    <main id="main" className="mx-auto w-full max-w-6xl px-4 py-10 sm:px-6 lg:py-16">
      <Wordmark direction={direction} name={PLACEHOLDER_NAME} size={40} />
      <h1 className="mt-6 text-2xl text-ink lg:text-3xl">{d.name}</h1>
      <p className="mt-2 max-w-[60ch] text-lg text-ink-soft">{d.tagline}</p>
      <p className="mt-3 max-w-[66ch] text-ink">{d.story}</p>

      <section aria-labelledby="tk-colour" className="mt-12">
        <h2 id="tk-colour" className="text-lg text-ink">Colour ({theme})</h2>
        <ul className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-5">
          {swatches.map(([name, hex, role]) => (
            <li key={name} className="rounded-control border border-line bg-field p-2">
              <span aria-hidden="true" className="block h-14 rounded-[calc(var(--radius-control)-4px)] border border-line" style={{ background: hex }} />
              <span className="mt-2 block text-sm font-semibold text-ink">{name}</span>
              <span className="block text-xs text-ink-soft tabular-nums">{hex} · {role}</span>
            </li>
          ))}
        </ul>
      </section>

      <section aria-labelledby="tk-type" className="mt-12">
        <h2 id="tk-type" className="text-lg text-ink">Type</h2>
        <p className="mt-1 text-sm text-ink-soft">
          Display {d.fonts.display} {d.type.displayWeight} · Text {d.fonts.text} · Figures {d.fonts.mono} · {d.fonts.licence}, self-hosted WOFF2, latin subset, swap
        </p>
        <div className="mt-4 flex flex-col gap-3">
          <p className="text-3xl text-ink" style={{ fontFamily: "var(--font-display)", fontWeight: "var(--display-weight)" as unknown as number, letterSpacing: "var(--display-tracking)" }}>
            Bring local solutions to the organisations that need them
          </p>
          <p className="text-xl text-ink" style={{ fontFamily: "var(--font-display)", fontWeight: "var(--display-weight)" as unknown as number }}>Cold chain for dairy co-ops</p>
          <p className="max-w-[66ch] text-base text-ink">Developers publish solutions to real problems. Organisations review them under NDA and agree the next step, and both sides follow the same tracker.</p>
          <p className="text-sm text-ink-soft">Registered 28 Sep 2026, 12:05 EAT · 4 business days left</p>
          <p className="font-mono text-lg text-ink">WYP2 C351 85CQ F7K3</p>
        </div>
      </section>

      <section aria-labelledby="tk-shape" className="mt-12 grid gap-8 lg:grid-cols-2">
        <div>
          <h2 id="tk-shape" className="text-lg text-ink">Radius and elevation</h2>
          <p className="mt-1 text-sm text-ink-soft">Controls {d.radius.control} px · panels {d.radius.panel} px. {d.elevation}</p>
          <div className="mt-4 flex flex-wrap items-start gap-4">
            <Panel className="w-56">
              <p className="font-semibold text-ink">Panel</p>
              <p className="mt-1 text-sm text-ink-soft">Card shadow</p>
            </Panel>
            <div className="w-56 rounded-panel bg-field p-5 shadow-overlay">
              <p className="font-semibold text-ink">Overlay</p>
              <p className="mt-1 text-sm text-ink-soft">Menus, dialogs, sheets</p>
            </div>
          </div>
          <div className="mt-4 flex flex-wrap gap-3">
            {/* Static specimens (a server page): the classes of Button, no handler. */}
            <button type="button" data-primary="" className={buttonClass("primary")}>Primary action</button>
            <button type="button" className={buttonClass("secondary")}>Secondary</button>
            <button type="button" className={buttonClass("danger")}>Withdraw</button>
          </div>
          <div className="mt-4">
            <Callout tone="info" title="Awaiting: you">
              <p className="text-ink">Your next step: Sign the mutual NDA</p>
            </Callout>
          </div>
        </div>
        <div>
          <h2 className="text-lg text-ink">Icons and status</h2>
          <p className="mt-1 text-sm text-ink-soft">{d.icons}</p>
          <div className="mt-4 flex flex-wrap gap-4 text-ink">
            {[HomeIcon, DiscoverIcon, IdeasIcon, EngagementsIcon, CompaniesIcon, LockIcon, SendIcon, ClockIcon].map((Icon, i) => (
              <Icon key={i} className="size-6" />
            ))}
          </div>
          <div className="mt-4 flex flex-wrap gap-x-5 gap-y-2">
            <Badge tone="ok" icon={<CheckIcon />}>Timestamped</Badge>
            <Badge tone="accent" solid icon={<ChipMark kind="current" />}>Your turn</Badge>
            <Badge tone="error" icon={<AlertIcon />}>Overdue</Badge>
            <Badge tone="neutral" icon={<InfoIcon />}>Seeded example</Badge>
          </div>
          <div className="mt-4 flex gap-3 text-ink">
            {(["completed", "current", "pending", "onHold", "overdue", "ended"] as const).map((k) => (
              <ChipMark key={k} kind={k} className="size-6" />
            ))}
          </div>
        </div>
      </section>

      <section aria-labelledby="tk-illu" className="mt-12 grid gap-8 lg:grid-cols-2">
        <div>
          <h2 id="tk-illu" className="text-lg text-ink">Empty-state illustration</h2>
          <p className="mt-1 text-sm text-ink-soft">{d.illustration}</p>
          <div className="mt-4 rounded-panel border border-line bg-field p-6">
            <EmptyIllustration direction={direction} />
            <EmptyStateFrame rule={false} sentence="Pitch one of your ideas to a company to start an engagement." action={<StandaloneLink href="#">Go to My ideas</StandaloneLink>} />
          </div>
        </div>
        <div>
          <h2 className="text-lg text-ink">Motion</h2>
          <p className="mt-1 max-w-[60ch] text-sm text-ink-soft">{d.motion.description}</p>
          <p className="mt-2 text-sm text-ink-soft tabular-nums">fast {d.motion.fast} · base {d.motion.base} · {d.motion.ease}</p>
          <p className="mt-4 text-sm text-ink-soft">Hover and press the buttons above: every control answers in this timing; reduced motion turns it off.</p>
        </div>
      </section>
    </main>
  );
}
