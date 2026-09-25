import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";

import { AuthShell } from "@/components/AuthShell";
import { IntlScope } from "@/components/IntlScope";

import { LinkSignIn } from "./LinkSignIn";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("link");
  return { title: t("title"), referrer: "no-referrer" };
}

export default function LinkPage() {
  return (
    <AuthShell>
      <IntlScope namespaces={["link", "fields", "validation", "errors"]}>
        <LinkSignIn />
      </IntlScope>
    </AuthShell>
  );
}
