import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";

import { EmptyState } from "@/components/ui/EmptyState";
import { PageHeader } from "@/components/ui/PageHeader";
import { Panel } from "@/components/ui/Panel";
import { RowList } from "@/components/ui/RowList";
import { Section } from "@/components/ui/Section";
import { ClientStrings } from "@/components/ClientStrings";
import { clientStrings } from "@/lib/i18n/client-strings";

import { AdminShell } from "../AdminShell";
import { staffContext } from "../staff";
import { getResearch } from "./data";
import { PageStepUp } from "./PageStepUp";
import { excerptsByNiche, nicheLabel, runNiches } from "./research";
import { CandidateRow, RunRow, SavedExcerpts } from "./Sections";
import { StartRun } from "./StartRun";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("adminResearch");
  return { title: t("pageTitle") };
}

/** How many runs the page lists (the API returns up to 100, newest first). */
const RUNS_SHOWN = 5;

/**
 * Research (REQ-RES-01, REQ-ADM-01; docs/spec/06 6.5; M2 walkthrough step 3): start a run for a niche in Kenya (the
 * screen's one primary action), the cards waiting for review, the recent runs and the saved excerpts runs read. Staff
 * admins only; a stale second factor asks for a fresh code first.
 */
export default async function ResearchPage() {
  const { role } = await staffContext();
  const t = await getTranslations("adminResearch");
  const header = <PageHeader title={t("title")} lead={t("lead")} focusable />;

  const refused = (sentence: string, action: string, href: string) => (
    <AdminShell role={role} current="research">
      {header}
      <div className="mt-8">
        <EmptyState sentence={sentence} action={action} href={href} />
      </div>
    </AdminShell>
  );
  if (role !== "admin") return refused(t("notAdmin"), t("notAdminAction"), "/admin");

  const loaded = await getResearch();
  if (loaded.kind === "forbidden") return refused(t("notAdmin"), t("notAdminAction"), "/admin");
  const strings = await clientStrings(["adminResearch"]);
  if (loaded.kind === "stepUp") {
    return (
      <AdminShell role={role} current="research">
        {header}
        <div className="mt-8">
          <ClientStrings strings={strings}>
            <PageStepUp />
          </ClientStrings>
        </div>
      </AdminShell>
    );
  }

  const { runs, candidates, sources, niches } = loaded.data;
  const options = runNiches(sources.excerpts, niches);
  const going = runs.find((run) => run.status === "running");
  const active = going ? { runId: going.id, name: nicheLabel(going.niche, niches) ?? "" } : null;

  return (
    <AdminShell role={role} current="research" wide>
      <div className="flex max-w-3xl flex-col gap-12">
        {header}

        {/* The screen's one panel: where its one primary action lives. */}
        <Panel as="section" variant="wash" aria-labelledby="start-run">
          <h2 id="start-run" className="text-lg text-ink">
            {t("start.heading")}
          </h2>
          <div className="mt-4">
            {options.length > 0 ? (
              <ClientStrings strings={strings}>
                <StartRun options={options} active={active} />
              </ClientStrings>
            ) : (
              <p className="text-ink">{t("start.noNiches")}</p>
            )}
          </div>
        </Panel>

        <Section title={t("queue.heading")} headingId="queue">
          {candidates.length > 0 ? (
            <RowList ordered aria-labelledby="queue">
              {candidates.map((candidate) => (
                <CandidateRow key={candidate.id} candidate={candidate} niches={niches} />
              ))}
            </RowList>
          ) : (
            <EmptyState sentence={t("queue.empty")} action={t("queue.emptyAction")} href="#run-niche" />
          )}
        </Section>

        {runs.length > 0 ? (
          <Section title={t("runs.heading")} headingId="runs">
            <RowList ordered aria-label={t("runs.listLabel")}>
              {runs.slice(0, RUNS_SHOWN).map((run) => (
                <RunRow key={run.id} run={run} niches={niches} />
              ))}
            </RowList>
          </Section>
        ) : null}

        {sources.excerpts.length > 0 ? (
          <SavedExcerpts
            groups={excerptsByNiche(sources.excerpts, options)}
            asOf={sources.as_of}
            total={sources.excerpts.length}
          />
        ) : null}
      </div>
    </AdminShell>
  );
}
