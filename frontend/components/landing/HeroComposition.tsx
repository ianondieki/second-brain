import { useTranslations } from "next-intl";
import type { CSSProperties } from "react";

import { PursueIcon } from "@/components/discover-icons";
import { Seal } from "@/components/brand/Seal";
import { Chip, ChipMark } from "@/components/tracker/Chip";
import { stepperSteps } from "@/components/tracker/model";
import { Stepper } from "@/components/tracker/Stepper";
import { Avatar } from "@/components/ui/Avatar";
import { Badge } from "@/components/ui/Badge";
import { CheckIcon, InfoIcon } from "@/components/ui/status-icons";

/** Each card's place in the one load sequence (globals.css .hero-rise): the tracker and the certificate rise; the
 * match arrives second (.hero-arrive), the seal draws third. */
const rise = (ms: number) => ({ "--rise-delay": `${ms}ms` }) as CSSProperties;

/**
 * The landing hero's product panel (D-55, D-66): the product's own parts in one petal frame, as a product screen
 * would show them: the tracker of an illustrative engagement on top, labelled "Demo data", with the next step's
 * countdown ticking; a scout match and the certificate below it. Nothing here is a live figure.
 *
 * One orchestrated story on load, CSS only, about 2.4 s (P23-2): the cards rise, the match arrives, the tracker
 * advances a stage and "Your turn" lights, the seal draws. The countdown is in days, hours and minutes, as the
 * product's (components/ui/Countdown.tsx), and its minutes step once a minute (globals.css .due-m: a registered integer,
 * no script; nothing moves in between, WCAG 2.2.2); the figure itself is decorative and its words are said once to
 * assistive technology. Reduced motion shows the end of the story in place and the countdown still.
 */
export function HeroComposition() {
  const t = useTranslations("landing.sample");
  const tt = useTranslations("tracker");
  // The story the card tells once on load (globals.css, "The hero's story"): the NDA is signed, the engagement moves
  // from Contact and NDA to Agreement, and it is the developer's turn. The stepper after the move is the real one;
  // the one before it lies over it, hidden from assistive technology, and fades as the move happens.
  const before = stepperSteps({ state: "NDA_PENDING", stage_group: "contact_nda", due: null });
  const after = stepperSteps({ state: "NEGOTIATION", stage_group: "agreement", due: null });
  const units = [
    { key: "days", value: "02" },
    { key: "hours", value: "14" },
    { key: "minutes", className: "due-m" },
  ] as const;
  return (
    <div data-hero-visual="" className="relative">
      <div aria-hidden="true" className="hero-glow pointer-events-none absolute -inset-x-8 -inset-y-12 -z-10" />
      <div className="rounded-[1.75rem] bg-accent-wash p-2 ring-1 ring-accent-line ring-inset sm:p-3">
        <article style={rise(0)} className="hero-rise relative rounded-[1.25rem] border border-line bg-field p-5 shadow-overlay sm:p-6">
          <div className="flex items-start justify-between gap-4">
            <p className="font-display text-xl leading-tight font-[600] text-ink sm:text-[1.375rem]">{t("ideaTitle")}</p>
            <span className="demo-label">{t("demo")}</span>
          </div>
          <p className="mt-1 text-sm text-ink-soft">{tt("withOrg", { org: t("org") })}</p>
          <p className="mt-4 flex flex-wrap items-center gap-2">
            <Avatar name="Achieng Otieno" size="sm" active />
            <Avatar name={t("org")} kind="org" size="sm" active />
            <span className="hero-chip grid">
              <Chip kind="current">{tt("document.agreement")}</Chip>
              <span aria-hidden="true" className="hero-before">
                <Chip kind="current">{t("stage")}</Chip>
              </span>
            </span>
            <Badge tone="warm" solid icon={<ChipMark kind="current" />} className="hero-turn">
              {tt("yourTurn")}
            </Badge>
          </p>
          <div className="mt-5 flex flex-col gap-3 rounded-2xl bg-paper px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
            <p className="text-sm font-semibold text-ink">
              {t("due")}
              <span className="sr-only"> {t("dueWords")}</span>
            </p>
            <div aria-hidden="true" className="flex gap-1.5">
              {units.map((unit) => (
                <span key={unit.key} className="due-box">
                  <span className={"due-n " + ("className" in unit ? unit.className : "")}>{"value" in unit ? unit.value : null}</span>
                  <span className="due-u">{t(`units.${unit.key}`)}</span>
                </span>
              ))}
            </div>
          </div>
          <div className="hero-steps relative mt-6">
            <Stepper steps={after} />
            <div aria-hidden="true" className="hero-before absolute inset-0">
              <Stepper steps={before} />
            </div>
          </div>
        </article>
        <div className="mt-2 grid grid-cols-1 gap-2 sm:mt-3 sm:grid-cols-2 sm:gap-3">
          <article className="hero-arrive hidden rounded-[1.25rem] border border-line bg-field p-5 sm:block">
            <p className="text-sm font-semibold text-ink">{t("matchTitle")}</p>
            <p className="mt-1 text-sm text-ink-soft">{t("matchOrg")}</p>
            <p className="mt-3 flex flex-wrap gap-2">
              <Badge tone="ok" icon={<PursueIcon />}>
                {t("matchFit")}
              </Badge>
              <Badge tone="neutral" icon={<InfoIcon />}>
                {t("matchWhy")}
              </Badge>
            </p>
          </article>
          <article style={rise(240)} className="hero-rise relative flex items-center gap-4 rounded-[1.25rem] border border-line bg-field p-4 sm:p-5">
            <Seal size={72} animate />
            <div className="min-w-0">
              <p className="text-sm font-semibold text-ink">{t("certTitle")}</p>
              <p className="mt-0.5 font-mono text-sm tracking-[0.04em] [overflow-wrap:anywhere] text-ink">WYP2C35185CQF7K3</p>
              <p className="mt-2">
                <Badge tone="ok" icon={<CheckIcon />}>
                  {t("certStatus")}
                </Badge>
              </p>
            </div>
          </article>
        </div>
      </div>
    </div>
  );
}
