import { useTranslations } from "next-intl";

import { Seal } from "@/components/brand/Seal";
import { Chip } from "@/components/tracker/Chip";
import { stepperSteps } from "@/components/tracker/model";
import { Stepper } from "@/components/tracker/Stepper";
import { Badge } from "@/components/ui/Badge";
import { Lattice } from "@/components/ui/Lattice";
import { ProgressBar } from "@/components/ui/ProgressBar";
import { CheckIcon, InfoIcon } from "@/components/ui/status-icons";
import { PursueIcon } from "@/components/discover-icons";

/**
 * The landing hero's product visual (D-52): a framed, layered composition of the product's own parts, the tracker,
 * the certificate and a scout match, on an illustrative engagement. Static and labelled as an example; nothing here
 * is a live figure. Stacked on phones, layered from 1024 px.
 */
export function HeroComposition() {
  const t = useTranslations("landing.sample");
  const tt = useTranslations("tracker");
  const steps = stepperSteps({ state: "NDA_PENDING", stage_group: "contact_nda", due: null });
  return (
    <div data-hero-visual="" className="relative overflow-hidden rounded-panel border border-line bg-wash-soft">
      <Lattice />
      <div className="relative flex flex-col gap-4 p-4 sm:p-6 lg:block lg:h-[29rem]">
        <article className="rounded-panel border border-line bg-field p-5 shadow-card lg:absolute lg:top-6 lg:right-6 lg:left-6">
          <div className="flex flex-wrap items-baseline justify-between gap-x-6 gap-y-1">
            <h3 className="text-base text-ink">{t("ideaTitle")}</h3>
            <Chip kind="current">{t("stage")}</Chip>
          </div>
          <p className="mt-0.5 text-sm text-ink-soft">{tt("withOrg", { org: t("org") })}</p>
          <ProgressBar value={1} max={5} label={tt("progress", { current: 2, total: 5, group: tt("group.contact_nda") })} className="mt-4" />
          <div className="mt-4">
            <Stepper steps={steps} />
          </div>
        </article>
        <article className="rounded-panel border border-line bg-field p-4 shadow-overlay lg:absolute lg:bottom-12 lg:left-6 lg:w-[38%]">
          <p className="text-sm font-semibold text-ink">{t("matchTitle")}</p>
          <p className="mt-0.5 text-sm text-ink-soft">{t("matchOrg")}</p>
          <p className="mt-3 flex flex-wrap gap-x-4 gap-y-1">
            <Badge tone="ok" icon={<PursueIcon />}>
              {t("matchFit")}
            </Badge>
            <Badge tone="neutral" icon={<InfoIcon />}>
              {t("matchWhy")}
            </Badge>
          </p>
        </article>
        <article data-lattice="" className="flex items-center gap-4 overflow-hidden rounded-panel border border-line bg-field p-4 shadow-overlay lg:absolute lg:right-6 lg:bottom-8 lg:w-[54%]">
          <Seal size={72} />
          <div className="min-w-0">
            <p className="text-sm font-semibold text-ink">{t("certTitle")}</p>
            <p className="mt-0.5 font-mono text-sm tracking-[0.06em] text-ink">WYP2C35185CQF7K3</p>
            <p className="mt-1.5">
              <Badge tone="ok" icon={<CheckIcon />}>
                {t("certStatus")}
              </Badge>
            </p>
          </div>
        </article>
        <p className="lg:absolute lg:bottom-2 lg:left-6">
          <Badge tone="neutral" icon={<InfoIcon />}>
            {t("label")}
          </Badge>
        </p>
      </div>
    </div>
  );
}
