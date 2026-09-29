import type { Metadata } from "next";
import { redirect } from "next/navigation";
import { getTranslations } from "next-intl/server";

import { DevNav } from "@/components/DevNav";
import { SignedInShell } from "@/components/SignedInShell";
import { requireMe } from "@/lib/api/server";
import { homeFor } from "@/lib/auth/routing";

import { browseDirectory, directoryOptions } from "./directory";
import { DirectoryFilters } from "./DirectoryFilters";
import { DirectoryResults } from "./DirectoryResults";
import { countOrgs, parseFilters } from "./filters";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("companies");
  return { title: t("pageTitle") };
}

/**
 * Developer › Companies (REQ-DIR-01, F1): the directory by niche with name search and niche, org type and county
 * filters, from GET /api/directory/orgs, rendered on the server. Developers only; others go to their own home.
 */
export default async function CompaniesPage({ searchParams }: PageProps<"/dev/companies">) {
  const me = await requireMe();
  const home = homeFor(me.side);
  if (home !== "/dev") redirect(home);
  const t = await getTranslations("companies");
  const filters = parseFilters(await searchParams);
  const [browse, { niches, filterOptions }] = await Promise.all([browseDirectory(filters), directoryOptions()]);
  const hasResults = browse.kind === "page" && countOrgs(browse.page) > 0;

  return (
    <SignedInShell homeHref={home} nav={<DevNav current="companies" />} wide>
      <h1 className="text-xl text-ink lg:text-2xl">{t("title")}</h1>
      <p className="mt-2 max-w-[62ch] text-ink-soft">{t("lead")}</p>
      <div className="mt-6 max-w-3xl">
        <DirectoryFilters filters={filters} niches={niches} options={filterOptions} showClear={hasResults} />
      </div>
      <div className="mt-8">
        {browse.kind === "page" ? (
          <DirectoryResults kind="page" page={browse.page} filters={filters} />
        ) : (
          <DirectoryResults kind="staleCursor" filters={filters} />
        )}
      </div>
    </SignedInShell>
  );
}
