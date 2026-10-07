import { useTranslations } from "next-intl";
import type { ComponentType, ReactNode } from "react";

import { Seal } from "@/components/brand/Seal";
import { BadgeCheckIcon, FileLockIcon, HouseIcon, InboxIcon, RouteIcon, type LucideProps } from "@/components/icons/lucide";
import { ChipMark } from "@/components/tracker/Chip";
import type { ChipKind } from "@/components/tracker/model";
import { Avatar } from "@/components/ui/Avatar";
import { Badge } from "@/components/ui/Badge";
import { Lattice } from "@/components/ui/Lattice";
import { CheckIcon, LockIcon } from "@/components/ui/status-icons";

import type { TourSide } from "./tour-store";

/**
 * The first-login tour's scenes (P23-2, D-52): one per step, a Lucide icon large in a petal disc with the saffron
 * spark, beside a miniature of what the step introduces, built from the product's own parts (the badge, the seal, the
 * tracker's marks, the avatar), the way the landing hero is. One thing in each is lit (`tour-lit`, globals.css) and
 * answers once when its slide arrives; everything else is quiet. Decorative (aria-hidden): the step's title and
 * sentence say it. Server components: the tour (a client component) receives them as props, so their markup travels
 * in the page, not in the route's JavaScript. Drawn on the tokens, so dark mode redraws them.
 */
export function tourScenes(side: TourSide): ReactNode[] {
  return side === "developer"
    ? [<DevHomeScene key="devHome" />, <DevIdeasScene key="devIdeas" />, <TrackerScene key="devTracker" />]
    : [<OrgInboxScene key="orgInbox" />, <OrgNdaScene key="orgNda" />, <TrackerScene key="orgTracker" org />];
}

/** The stage: the icon's disc in the corner, the miniature over the rest of it. */
function Stage({ Icon, children }: { Icon: ComponentType<LucideProps>; children: ReactNode }) {
  return (
    <div aria-hidden="true" className="tour-stage">
      <span className="tour-disc">
        <Icon className="size-14" />
      </span>
      <div className="tour-mini">{children}</div>
    </div>
  );
}

const card = "rounded-xl bg-field p-3 ring-1 ring-line";

function DevHomeScene() {
  const t = useTranslations("devHome.stats");
  return (
    <Stage Icon={HouseIcon}>
      <div className="grid grid-cols-2 gap-2.5">
        <div className={card}>
          <p className="text-xs font-semibold text-ink-soft">{t("ideas")}</p>
          <p className="mt-1 font-display text-2xl leading-none font-[720] text-ink tabular-nums">3</p>
        </div>
        <div className={`${card} tour-lit shadow-card ring-2 ring-accent`}>
          <p className="flex items-center gap-1.5 text-xs font-semibold text-ink">
            <span className="size-2 shrink-0 rounded-full bg-flourish" />
            {t("needsYou")}
          </p>
          <p className="mt-1 font-display text-2xl leading-none font-[720] text-accent tabular-nums">1</p>
        </div>
      </div>
    </Stage>
  );
}

function DevIdeasScene() {
  const t = useTranslations("landing.sample");
  return (
    <Stage Icon={BadgeCheckIcon}>
      <div className="overflow-hidden rounded-xl bg-field shadow-card ring-1 ring-line">
        <Lattice />
        <div className="flex items-center gap-2.5 p-3">
          <Seal size={44} animate />
          <div className="min-w-0">
            <p className="text-xs leading-tight font-semibold text-ink">{t("certTitle")}</p>
            <p className="mt-0.5 font-mono text-xs text-ink-soft">9f2c…41ab</p>
            <Badge tone="ok" icon={<CheckIcon />} className="mt-1.5 text-xs!">
              {t("certStatus")}
            </Badge>
          </div>
        </div>
      </div>
    </Stage>
  );
}

const MARKS: ChipKind[] = ["completed", "completed", "current", "pending", "pending"];

/** The tracker in miniature: the five stages as marks on a line, the current one with "Your turn" lit. */
function TrackerScene({ org = false }: { org?: boolean }) {
  const t = useTranslations("tracker");
  const s = useTranslations("landing.sample");
  return (
    <Stage Icon={RouteIcon}>
      <div className={`${card} shadow-card`}>
        <p className="truncate text-xs font-semibold text-ink">{org ? s("ideaTitle") : t("withOrg", { org: s("org") })}</p>
        <ol className="mt-3 flex items-center">
          {MARKS.map((kind, i) => (
            <li key={i} className="flex flex-1 items-center last:flex-none">
              <ChipMark
                kind={kind}
                className={`size-5 rounded-full bg-field ${kind === "pending" ? "text-ink-soft" : "text-accent"} ${kind === "current" ? "ring-4 ring-accent-wash" : ""}`}
              />
              {i < MARKS.length - 1 ? <span className={`mx-1 h-0.5 flex-1 rounded-full ${i < 2 ? "bg-accent" : "bg-line"}`} /> : null}
            </li>
          ))}
        </ol>
        <p className="mt-3 flex flex-wrap items-center justify-between gap-2">
          <span className="text-xs font-bold text-ink">{t("group.agreement")}</span>
          <Badge tone="warm" solid icon={<ChipMark kind="current" />} className="tour-lit text-xs!">
            {t("yourTurn")}
          </Badge>
        </p>
      </div>
    </Stage>
  );
}

function OrgInboxScene() {
  const s = useTranslations("landing.sample");
  const t = useTranslations("inbox");
  return (
    <Stage Icon={InboxIcon}>
      <div className={`${card} tour-lit tour-arrive shadow-card`}>
        <p className="text-xs leading-snug font-semibold text-ink">{s("ideaTitle")}</p>
        <p className="mt-2 flex items-center justify-between gap-2">
          <span className="flex min-w-0 items-center gap-1.5 text-xs text-ink-soft">
            <Avatar name="Achieng Otieno" size="sm" className="max-sm:hidden" />
            <span className="truncate">{t("from", { handle: "@achieng" })}</span>
          </span>
          <Badge tone="accent" className="text-xs!">
            {t("stage.SUBMITTED")}
          </Badge>
        </p>
      </div>
    </Stage>
  );
}

function OrgNdaScene() {
  const s = useTranslations("landing.sample");
  const f = useTranslations("ideaFields");
  const v = useTranslations("ideaViews");
  return (
    <Stage Icon={FileLockIcon}>
      <div className={`${card} shadow-card`}>
        <p className="text-xs leading-snug font-semibold text-ink">{s("ideaTitle")}</p>
        <Badge tone="accent" solid icon={<LockIcon />} className="tour-lit mt-1.5 text-xs!">
          {f("confidentialBadge")}
        </Badge>
        <div className="mt-2 border-t border-line pt-1.5 text-xs leading-snug">
          <p className="text-ink-soft">{v("title")}</p>
          <p className="font-semibold text-ink">{v("viewer", { name: "Wanjiru K.", org: s("org") })}</p>
        </div>
      </div>
    </Stage>
  );
}
