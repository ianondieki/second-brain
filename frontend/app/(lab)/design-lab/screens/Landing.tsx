import Link from "next/link";
import { getTranslations } from "next-intl/server";

import { AuthShell } from "@/components/AuthShell";
import { Chip } from "@/components/tracker/Chip";
import { stepperSteps } from "@/components/tracker/model";
import { Stepper } from "@/components/tracker/Stepper";
import { Badge } from "@/components/ui/Badge";
import { textLinkClass } from "@/components/ui/Button";
import { ButtonLink } from "@/components/ui/ButtonLink";
import { InfoIcon } from "@/components/ui/icons";

import { DETAIL } from "../fixtures";

/**
 * The public landing hero exactly as app/(public)/page.tsx composes it (AuthShell, title, lead, the one primary
 * action), plus the live product visual the brief asks for: the real tracker stepper on a fixture engagement, in a
 * floating panel. Copy is the product's own (locales/en.json `landing`); the visual is labelled a demo.
 */
export async function LandingScreen() {
  const t = await getTranslations("landing");
  const tt = await getTranslations("tracker");
  const steps = stepperSteps({ state: DETAIL.state, stage_group: DETAIL.stage_group, due: DETAIL.due });
  return (
    <AuthShell landing>
      <h1 className="text-2xl text-ink lg:text-3xl">{t("title")}</h1>
      <p className="mt-4 max-w-[60ch] text-lg text-ink-soft">{t("lead")}</p>
      <div className="mt-8 flex flex-col items-start gap-4">
        <ButtonLink href="/signup" variant="primary">
          {t("signUp")}
        </ButtonLink>
        <p className="text-ink">
          {t.rich("haveAccount", {
            login: (chunks) => (
              <Link href="/login" className={textLinkClass}>
                {chunks}
              </Link>
            ),
          })}
        </p>
      </div>
      <div data-hero-visual="" className="mt-12 rounded-panel border border-line bg-field p-5 sm:p-6">
        <div className="flex flex-wrap items-baseline justify-between gap-x-6 gap-y-1">
          <p className="text-base font-semibold text-ink">{DETAIL.proposal_title}</p>
          <Chip kind="current">{DETAIL.stage_label}</Chip>
        </div>
        <p className="mt-1 text-sm text-ink-soft">{tt("withOrg", { org: DETAIL.org_name })}</p>
        <div className="mt-5">
          <Stepper steps={steps} />
        </div>
        <p className="mt-5">
          <Badge tone="neutral" icon={<InfoIcon />}>
            Seeded example
          </Badge>
        </p>
      </div>
    </AuthShell>
  );
}
