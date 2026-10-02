import { redirect } from "next/navigation";
import { getTranslations } from "next-intl/server";

import { DevNav } from "@/components/DevNav";
import { ClientStrings } from "@/components/ClientStrings";
import { SignedInShell } from "@/components/SignedInShell";
import { EmptyState } from "@/components/ui/EmptyState";
import { PageHeader } from "@/components/ui/PageHeader";
import { BackLink } from "@/components/ui/BackLink";
import { requireMe } from "@/lib/api/server";
import { clientStrings } from "@/lib/i18n/client-strings";
import { homeFor } from "@/lib/auth/routing";

import { chipsOf, overlapKey } from "../checks";
import { editorOptions, lastOverlap, linkableProblem, myIdea } from "../data";
import {
  BASE_PATH,
  ideaHref,
  type Step,
} from "../ideas";
import { editableVersion, stateFromVersion, stateWithProblem } from "../versions";
import { CheckAnswer } from "./CheckAnswer";
import { Editor } from "./Editor";

/**
 * The editor's page for a new idea (id null) or one of yours: developers only; a hidden idea cannot change, so it
 * opens its own page instead. Everything the steps need is fetched here, on the server. A new idea can start with a
 * published problem linked (`problemId`, from Discover); an id that is not one is ignored.
 */
export async function EditorScreen({ id, step, problemId = null }: { id: string | null; step: Step; problemId?: string | null }) {
  const me = await requireMe();
  const home = homeFor(me.side);
  if (home !== "/dev") redirect(home);
  const t = await getTranslations("ideaEditor");
  const ideas = await getTranslations("ideas");
  const [idea, options, problem, overlap] = await Promise.all([
    id ? myIdea(id) : Promise.resolve(null),
    editorOptions(),
    !id && problemId ? linkableProblem(problemId) : Promise.resolve(null),
    id ? lastOverlap(id) : Promise.resolve(null),
  ]);

  if (id && !idea) {
    return (
      <SignedInShell homeHref={home} nav={<DevNav current="ideas" />}>
        <PageHeader title={t("pageTitleEdit")} />
        <EmptyState className="mt-8" sentence={ideas("notFound")} action={ideas("back")} href={BASE_PATH} />
      </SignedInShell>
    );
  }
  if (idea && (idea.status === "hidden" || idea.status === "archived")) redirect(ideaHref(idea.id));

  const version = idea ? editableVersion(idea) : null;
  // Today's last overlap check, drawn here so the page ships no script for it (the checks card loads on a press).
  const checks = await getTranslations("ideaChecks");
  const assistant = await getTranslations("ideaAssistant");
  const lastCheck = overlap && (
    <CheckAnswer
      tone={overlap.band === "none" ? "clear" : "note"}
      sentence={checks(overlapKey(overlap), { count: overlap.compared })}
      detail={overlap.explanation}
      chips={chipsOf(overlap).map((chip) => ({ label: assistant(chip), quiet: chip === "demoFallback" }))}
      caption={checks("lastToday")}
    />
  );
  return (
    <SignedInShell homeHref={home} nav={<DevNav current="ideas" />}>
      <BackLink href={idea ? ideaHref(idea.id) : BASE_PATH}>{idea ? t("backToIdea") : ideas("back")}</BackLink>
      <ClientStrings strings={await clientStrings(["ideaEditor", "ideaFields", "ideaAssistant", "ideaChecks"])}>
        <Editor
          id={idea?.id ?? null}
          hasDraft={idea?.draft != null}
          initial={problem ? stateWithProblem(problem) : stateFromVersion(version)}
          attachments={version?.confidential.attachments ?? []}
          step={step}
          niches={options.niches}
          counties={options.counties}
          attestations={options.attestations}
          problems={options.problems}
          lastOverlap={lastCheck || undefined}
        />
      </ClientStrings>
    </SignedInShell>
  );
}
