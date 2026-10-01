import { useTranslations } from "next-intl";

import { Seal } from "@/components/brand/Seal";
import { Avatar } from "@/components/ui/Avatar";
import { Chip, ChipMark } from "@/components/tracker/Chip";
import { stepperSteps } from "@/components/tracker/model";
import { Stepper } from "@/components/tracker/Stepper";
import { Badge } from "@/components/ui/Badge";
import { Lattice } from "@/components/ui/Lattice";
import { CheckIcon, InfoIcon } from "@/components/ui/status-icons";
import { PursueIcon } from "@/components/discover-icons";

/**
 * The landing hero's product visual (D-52): the product's own parts, the tracker, a scout match and the certificate,
 * in a browser frame over a soft backdrop, on an illustrative engagement. Static and labelled as an example; nothing
 * here is a live figure. The cards stack on phones and layer with a little depth from 1024 px; every word is at
 * least 13 px.
 */
export function HeroComposition() {
  const t = useTranslations("landing.sample");
  const tt = useTranslations("tracker");
  const steps = stepperSteps({ state: "NDA_PENDING", stage_group: "contact_nda", due: null });
  return (
    <div data-hero-visual="" data-hero-backdrop="" className="rounded-panel p-3 sm:p-6 lg:p-6">
      <div className="overflow-hidden rounded-panel border border-line bg-paper shadow-overlay">
        <Lattice />
        {/* The browser's chrome: three dots and the address, decorative. */}
        <div aria-hidden="true" className="flex items-center gap-3 border-b border-line bg-field px-4 py-2.5">
          <span className="flex gap-1.5">
            <span className="size-2.5 rounded-full bg-line" />
            <span className="size-2.5 rounded-full bg-line" />
            <span className="size-2.5 rounded-full bg-line" />
          </span>
          <span className="flex min-w-0 flex-1 justify-center">
            <span className="truncate rounded-full border border-line bg-paper px-3 py-0.5 text-sm text-ink-soft">wazo · /dev/engagements</span>
          </span>
        </div>
        <div className="relative flex flex-col gap-4 p-4 sm:p-6 lg:block lg:h-[29rem] lg:p-8">
          <article className="rounded-panel border border-line bg-field p-5 shadow-card lg:absolute lg:top-8 lg:right-[33%] lg:left-8 lg:p-7">
            <div className="flex flex-wrap items-baseline justify-between gap-x-6 gap-y-1">
              <p className="text-base font-semibold text-ink lg:text-lg">{t("ideaTitle")}</p>
              <Chip kind="current">{t("stage")}</Chip>
            </div>
            <p className="mt-0.5 text-sm text-ink-soft lg:text-base">{tt("withOrg", { org: t("org") })}</p>
            <p className="mt-3 flex items-center gap-2 text-sm text-ink-soft">
              <Avatar name="Achieng Otieno" size="sm" active />
              <Avatar name={t("org")} kind="org" size="sm" active />
              <Badge tone="warm" solid icon={<ChipMark kind="current" />}>
                {tt("yourTurn")}
              </Badge>
            </p>
            <div className="mt-5 lg:mt-7">
              <Stepper steps={steps} />
            </div>
          </article>
          <article className="rounded-panel border border-line bg-field p-4 shadow-overlay lg:absolute lg:top-8 lg:right-8 lg:w-[29%] lg:rotate-1 lg:p-5">
            <p className="text-sm font-semibold text-ink lg:text-base">{t("matchTitle")}</p>
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
          <article data-lattice="" className="flex items-center gap-4 overflow-hidden rounded-panel border border-line bg-field p-4 shadow-overlay lg:absolute lg:right-8 lg:bottom-8 lg:w-[44%] lg:-rotate-1 lg:p-5">
            <Seal size={84} />
            <div className="min-w-0">
              <p className="text-sm font-semibold text-ink lg:text-base">{t("certTitle")}</p>
              <p className="mt-0.5 font-mono text-sm tracking-[0.06em] text-ink">WYP2C35185CQF7K3</p>
              <p className="mt-1.5">
                <Badge tone="ok" icon={<CheckIcon />}>
                  {t("certStatus")}
                </Badge>
              </p>
            </div>
          </article>
          <p className="lg:absolute lg:bottom-3 lg:left-8">
            <Badge tone="neutral" icon={<InfoIcon />}>
              {t("label")}
            </Badge>
          </p>
        </div>
      </div>
    </div>
  );
}
