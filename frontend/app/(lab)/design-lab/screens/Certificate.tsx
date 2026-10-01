import { getTranslations } from "next-intl/server";

import { DevNav } from "@/components/DevNav";
import { SignedInShell } from "@/components/SignedInShell";
import { ButtonLink } from "@/components/ui/ButtonLink";
import { PageHeader } from "@/components/ui/PageHeader";

import { Certificate } from "@/app/(app)/dev/ideas/[id]/Certificate";
import { IdeaStatusBadge } from "@/app/(app)/dev/ideas/IdeaStatusBadge";

import { IDEA, ME } from "../fixtures";

/** The idea page's header, actions and its real Certificate section (the sheet), on fixture data. */
export async function CertificateScreen() {
  const t = await getTranslations("ideas");
  return (
    <SignedInShell homeHref="/dev" nav={<DevNav current="ideas" />}>
      <PageHeader back={{ href: "/dev/ideas", label: t("back") }} title={IDEA.current!.teaser.title!}>
        <p className="mt-3 flex flex-wrap items-center gap-x-5 gap-y-1">
          <IdeaStatusBadge status="published" />
          <span className="text-sm text-ink-soft">{t("version", { number: 2 })}</span>
        </p>
      </PageHeader>
      <div className="mt-6 flex flex-col gap-3 sm:flex-row sm:flex-wrap">
        <ButtonLink href="#" variant="primary">
          Pitch to companies
        </ButtonLink>
        <ButtonLink href="#" variant="secondary">
          {t("edit")}
        </ButtonLink>
      </div>
      <Certificate idea={IDEA} ownerName={ME.user.display_name} />
    </SignedInShell>
  );
}
