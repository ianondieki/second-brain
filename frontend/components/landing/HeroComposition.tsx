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

/** Each card's place in the one load sequence (globals.css .hero-rise): the tracker, then the match, then the seal. */
const rise = (ms: number) => ({ "--rise-delay": `${ms}ms` }) as CSSProperties;

/**
 * The landing hero's product visual (D-55): three of the product's own parts on the night band, the tracker of an
 * illustrative engagement in front, a scout match behind it and the certificate below, over one soft bloom light.
 * Static and labelled as an example; nothing here is a live figure. The cards stack on phones (the match from 640 px)
 * and layer from 1024 px; they rise into place once on load (reduced motion: in place).
 */
export function HeroComposition() {
  const t = useTranslations("landing.sample");
  const tt = useTranslations("tracker");
  const steps = stepperSteps({ state: "NDA_PENDING", stage_group: "contact_nda", due: null });
  return (
    <div data-hero-visual="" className="relative">
      <div aria-hidden="true" className="hero-glow pointer-events-none absolute -inset-x-10 -inset-y-16 -z-10" />
      <div className="relative flex flex-col gap-4 lg:block lg:h-[35rem]">
        <article
          style={rise(120)}
          className="hero-rise order-2 hidden rounded-[1.25rem] border border-line bg-field p-5 shadow-overlay sm:block lg:absolute lg:top-0 lg:right-2 lg:w-[60%] lg:rotate-[2deg] lg:p-5"
        >
          <p className="text-sm font-semibold text-ink lg:text-base">{t("matchTitle")}</p>
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
          className="hero-rise relative order-1 rounded-[1.25rem] border border-line bg-field p-5 shadow-overlay sm:p-6 lg:absolute lg:top-[9.25rem] lg:right-0 lg:left-0 lg:z-10 lg:p-6"
        >
          <div className="flex flex-wrap items-baseline justify-between gap-x-6 gap-y-1">
            <p className="font-display text-lg font-[700] tracking-[-0.015em] text-ink lg:text-xl">{t("ideaTitle")}</p>
            <Chip kind="current">{t("stage")}</Chip>
          </div>
          <p className="mt-0.5 text-sm text-ink-soft lg:text-base">{tt("withOrg", { org: t("org") })}</p>
          <p className="mt-4 flex items-center gap-2 text-sm text-ink-soft">
            <Avatar name="Achieng Otieno" size="sm" active />
            <Avatar name={t("org")} kind="org" size="sm" active />
            <Badge tone="warm" solid icon={<ChipMark kind="current" />}>
              {tt("yourTurn")}
            </Badge>
          </p>
          <div className="mt-6 lg:mt-7">
            <Stepper steps={steps} />
          </div>
        </article>
        <article
          style={rise(240)}
          className="hero-rise relative order-3 flex items-center gap-4 rounded-[1.25rem] border border-line bg-field p-4 shadow-overlay lg:absolute lg:bottom-0 lg:left-10 lg:z-20 lg:w-[58%] lg:-rotate-[1.5deg] lg:p-5"
        >
          <Seal size={76} />
          <div className="min-w-0">
            <p className="text-sm font-semibold text-ink lg:text-base">{t("certTitle")}</p>
            <p className="mt-0.5 font-mono text-sm tracking-[0.06em] text-ink">WYP2C35185CQF7K3</p>
            <p className="mt-2">
              <Badge tone="ok" icon={<CheckIcon />}>
                {t("certStatus")}
              </Badge>
            </p>
          </div>
        </article>
      </div>
      <p className="mt-5 text-sm text-night-soft lg:mt-6">
        <InfoIcon aria-hidden="true" className="mr-1.5 inline size-4 align-[-3px]" />
        {t("label")}
      </p>
    </div>
  );
}
