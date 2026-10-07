import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { getLocale, getTranslations } from "next-intl/server";

import { PublicFrame } from "@/components/landing/PublicFrame";
import { BackLink } from "@/components/ui/BackLink";
import { ButtonLink } from "@/components/ui/ButtonLink";
import { formatDay } from "@/lib/format";
import { nicheLabel, publicProblem } from "@/lib/public/public-data";
import { loginHref } from "@/lib/return-path";

export async function generateMetadata({ params }: PageProps<"/explore/problems/[id]">): Promise<Metadata> {
  const id = (await params).id;
  const [read, tOg] = await Promise.all([publicProblem(id), getTranslations("og")]);
  if (read.kind !== "found") return {};
  const { title, statement } = read.problem;
  return {
    title,
    description: statement.length > 160 ? `${statement.slice(0, 157).trimEnd()}…` : statement,
    openGraph: {
      title,
      images: [{ url: `/og/problem/${encodeURIComponent(id)}`, width: 1200, height: 630, alt: tOg("problemAlt", { title }) }],
    },
  };
}

/**
 * A public problem (P24; REQ-UX-03): GET /api/public/problems/{id}, rendered on the server, for a visitor from Explore
 * or a shared link. Its source as the eyebrow, the title, where and in which niche, when; the statement and who it
 * affects; the organisation's verification level when an organisation posted it (never a name: the directory is
 * signed-in); "Seeded example" on demo data. One primary action, "Create an account to answer this", and a way to log
 * in that comes back to the signed-in problem page. A problem that is not public is not found.
 */
export default async function PublicProblemPage({ params }: PageProps<"/explore/problems/[id]">) {
  const id = (await params).id;
  const [read, t, locale] = await Promise.all([publicProblem(id), getTranslations("problemPage"), getLocale()]);
  if (read.kind === "notFound") notFound();
  if (read.kind === "unavailable") throw new Error(t("unavailable"));
  const problem = read.problem;
  const niche = nicheLabel(problem.niche);
  return (
    <PublicFrame>
      <article aria-labelledby="problem-title" data-public-problem={problem.id} className="mx-auto w-full max-w-3xl px-4 pt-8 pb-20 sm:px-6 lg:pt-12 lg:pb-28">
        <BackLink href="/explore">{t("back")}</BackLink>
        <p className="eyebrow mt-8">{t(`source.${problem.source}`)}</p>
        <h1 id="problem-title" className="mt-4 text-[2.25rem] leading-[1.08] [overflow-wrap:anywhere] text-ink lg:text-[3rem]">
          {problem.title}
        </h1>
        <p className="mt-5 flex flex-wrap items-center gap-x-4 gap-y-2 text-ink-soft">
          <span className="font-semibold text-ink">{problem.county?.name ?? t("nationwide")}</span>
          {niche ? <span>{niche}</span> : null}
          {problem.posted_at ? (
            <time dateTime={problem.posted_at}>{t("posted", { date: formatDay(locale, problem.posted_at) })}</time>
          ) : null}
          {problem.seeded ? <span className="demo-label">{t("seeded")}</span> : null}
        </p>
        {problem.organisation ? (
          <p className="mt-3 text-sm font-semibold text-ink" data-problem="organisation">
            {t(`organisation.${problem.organisation.verification}`)}
          </p>
        ) : null}

        <section aria-labelledby="problem-statement" className="mt-10 border-t border-line pt-8">
          <h2 id="problem-statement" className="text-xl text-ink">
            {t("statement")}
          </h2>
          <p className="mt-3 max-w-[68ch] text-lg whitespace-pre-line [overflow-wrap:anywhere] text-ink">{problem.statement}</p>
          {problem.affected_group ? (
            <>
              <h2 className="mt-8 text-xl text-ink">{t("affected")}</h2>
              <p className="mt-3 max-w-[68ch] [overflow-wrap:anywhere] text-ink">{problem.affected_group}</p>
            </>
          ) : null}
        </section>

        <div className="mt-12 rounded-[1.25rem] border border-line bg-field p-6 sm:p-8">
          <p className="max-w-[52ch] text-ink-soft">{t("lead")}</p>
          <div className="mt-5 flex flex-col gap-4 sm:flex-row sm:items-center sm:gap-6">
            <ButtonLink href="/signup" variant="primary">
              {t("answer")}
            </ButtonLink>
            <p className="text-ink-soft">
              {t.rich("haveAccount", {
                login: (chunks) => (
                  <Link href={loginHref(`/problems/${problem.id}`)} className="py-3 font-semibold text-ink underline decoration-1 hover:decoration-2">
                    {chunks}
                  </Link>
                ),
              })}
            </p>
          </div>
        </div>
      </article>
    </PublicFrame>
  );
}
