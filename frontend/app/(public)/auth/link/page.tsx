import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";

import { AuthShell } from "@/components/AuthShell";

import { LinkSignIn } from "./LinkSignIn";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("link");
  return { title: t("title"), referrer: "no-referrer" };
}

export default function LinkPage() {
  return (
    <AuthShell>
      <LinkSignIn />
    </AuthShell>
  );
}
