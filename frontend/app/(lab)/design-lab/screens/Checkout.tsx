import { getLocale, getTranslations } from "next-intl/server";

import { ClientStrings } from "@/components/ClientStrings";
import { SignedInShell } from "@/components/SignedInShell";
import { Badge } from "@/components/ui/Badge";
import { InfoIcon } from "@/components/ui/icons";
import { PageHeader } from "@/components/ui/PageHeader";
import { clientStrings } from "@/lib/i18n/client-strings";

import { SamplePrices } from "@/app/(app)/billing/SamplePrices";

import { LabCheckout } from "./LabCheckout";

/** The simulated M-Pesa checkout as app/(app)/billing/upgrade/page.tsx composes it; `?variant=success` shows the end. */
export async function CheckoutScreen({ succeeded }: { succeeded: boolean }) {
  const t = await getTranslations("billing");
  const tc = await getTranslations("checkout");
  return (
    <SignedInShell homeHref="/dev">
      <PageHeader back={{ href: "/billing", label: tc("back") }} title={tc("pageTitle", { plan: "Pro (monthly)" })}>
        <p className="mt-3">
          <Badge tone="neutral" icon={<InfoIcon />}>
            {tc("simulatedTag")}
          </Badge>
        </p>
      </PageHeader>
      <ClientStrings strings={await clientStrings(["checkout"])}>
        <LabCheckout locale={await getLocale()} sample={<SamplePrices label={t("samplePrices")} />} succeeded={succeeded} />
      </ClientStrings>
    </SignedInShell>
  );
}
