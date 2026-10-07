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
 * The landing hero's product visual (D-55): three of the product's own parts on the night band, the tracker of an
 * illustrative engagement in front, a scout match behind it and the certificate below, over one soft bloom light.
 * Static and labelled as an example; nothing here is a live figure. The cards stack on phones (the match from 640 px)
 * and layer from 1280 px, where the column is wide enough for the tracker's five stages. One orchestrated story on
 * load, CSS only, about 2.4 s (P23-2): the cards rise, the match arrives, the tracker advances a stage and "Your
 * turn" lights, the seal draws. Reduced motion shows the end of the story in place.
 */
export function HeroComposition() {
  const t = useTranslations("landing.sample");
  const tt = useTranslations("tracker");
  // The story the card tells once on load (globals.css, "The hero's story"): the NDA is signed, the engagement moves
  // from Contact and NDA to Agreement, and it is the developer's turn. The stepper after the move is the real one;
  // the one before it lies over it, hidden from assistive technology, and fades as the move happens.
  const before = stepperSteps({ state: "NDA_PENDING", stage_group: "contact_nda", due: null });
  const after = stepperSteps({ state: "NEGOTIATION", stage_group: "agreement", due: null });
  return (
    <div data-hero-visual="" className="relative max-w-2xl xl:max-w-none">
      <div aria-hidden="true" className="hero-glow pointer-events-none absolute -inset-x-10 -inset-y-16 -z-10" />
      <div className="relative flex flex-col gap-4 xl:block xl:h-[35rem]">
        <article
          className="hero-arrive order-2 hidden rounded-[1.25rem] border border-line bg-field p-5 shadow-overlay sm:block xl:absolute xl:top-0 xl:right-2 xl:w-[60%] xl:rotate-[2deg] xl:p-5"
        >
          <p className="text-sm font-semibold text-ink xl:text-base">{t("matchTitle")}</p>
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
        <article
          style={rise(0)}
          className="hero-rise relative order-1 rounded-[1.25rem] border border-line bg-field p-5 shadow-overlay sm:p-6 xl:absolute xl:top-[9.25rem] xl:right-0 xl:left-0 xl:z-10 xl:p-6"
        >
          <div className="flex flex-wrap items-baseline justify-between gap-x-6 gap-y-1">
            <p className="font-display text-lg font-[700] tracking-[-0.015em] text-ink xl:text-xl">{t("ideaTitle")}</p>
            <span className="hero-chip grid">
              <Chip kind="current">{tt("document.agreement")}</Chip>
              <span aria-hidden="true" className="hero-before">
                <Chip kind="current">{t("stage")}</Chip>
              </span>
            </span>
          </div>
          <p className="mt-0.5 text-sm text-ink-soft xl:text-base">{tt("withOrg", { org: t("org") })}</p>
          <p className="mt-4 flex items-center gap-2 text-sm text-ink-soft">
            <Avatar name="Achieng Otieno" size="sm" active />
            <Avatar name={t("org")} kind="org" size="sm" active />
            <Badge tone="warm" solid icon={<ChipMark kind="current" />} className="hero-turn">
              {tt("yourTurn")}
            </Badge>
          </p>
          <div className="hero-steps relative mt-6 xl:mt-7">
            <Stepper steps={after} />
            <div aria-hidden="true" className="hero-before absolute inset-0">
              <Stepper steps={before} />
            </div>
          </div>
        </article>
        <article
          style={rise(240)}
          className="hero-rise relative order-3 flex items-center gap-4 rounded-[1.25rem] border border-line bg-field p-4 shadow-overlay xl:absolute xl:bottom-0 xl:left-10 xl:z-20 xl:w-[58%] xl:-rotate-[1.5deg] xl:p-5"
        >
          <Seal size={76} animate />
          <div className="min-w-0">
            <p className="text-sm font-semibold text-ink xl:text-base">{t("certTitle")}</p>
            <p className="mt-0.5 font-mono text-sm tracking-[0.06em] text-ink">WYP2C35185CQF7K3</p>
            <p className="mt-2">
              <Badge tone="ok" icon={<CheckIcon />}>
                {t("certStatus")}
              </Badge>
            </p>
          </div>
        </article>
      </div>
      <p className="mt-5 text-sm text-night-soft xl:mt-6">
        <InfoIcon aria-hidden="true" className="mr-1.5 inline size-4 align-[-3px]" />
        {t("label")}
      </p>
    </div>
  );
}
