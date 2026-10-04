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

// The editor's layout (P20), drawn from the server so the editor's client bundle carries none of it (the edit route
// sits at the JS budget). Every step keeps a 42 rem column (the stepper, the fields, the buttons); from 1024 px step 1
// (the one step holding the teaser checks) is two columns: the problem card, then the public teaser on the left, the
// teaser checks and the writing assistant in a rail on the right from the top, the order of the page unchanged (the
// problem card spans three rows, the last a flexible one, so the rail's two cards stay together). The two tools sit
// on the canvas with a hairline, quieter than the white form cards. Tailwind reads these classes as written, so each
// selector is spelled out ("step 1" is the fieldset's child holding the checks).
const EDITOR_LAYOUT = [
  "max-w-4xl [&_fieldset>*]:max-w-2xl",
  "[&_fieldset>div:has(#checks-title)>section:nth-of-type(n+2)]:bg-paper",
  "lg:[&_fieldset>div:has(#checks-title)]:grid lg:[&_fieldset>div:has(#checks-title)]:max-w-none",
  "lg:[&_fieldset>div:has(#checks-title)]:grid-cols-[minmax(0,1fr)_17rem]",
  "lg:[&_fieldset>div:has(#checks-title)]:grid-rows-[auto_auto_1fr_auto] lg:[&_fieldset>div:has(#checks-title)]:items-start",
  "lg:[&_fieldset>div:has(#checks-title)>div:first-child]:row-span-3",
  "lg:[&_fieldset>div:has(#checks-title)>section:nth-of-type(1)]:col-start-1 lg:[&_fieldset>div:has(#checks-title)>section:nth-of-type(1)]:row-start-4",
  "lg:[&_fieldset>div:has(#checks-title)>section:nth-of-type(2)]:col-start-2 lg:[&_fieldset>div:has(#checks-title)>section:nth-of-type(2)]:row-start-1",
  "lg:[&_fieldset>div:has(#checks-title)>section:nth-of-type(3)]:col-start-2 lg:[&_fieldset>div:has(#checks-title)>section:nth-of-type(3)]:row-start-2",
  "lg:has-[#checks-title]:[&_fieldset>div:last-child]:max-w-none",
].join(" ");

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
    <SignedInShell homeHref={home} nav={<DevNav current="ideas" />} wide>
      <div className={EDITOR_LAYOUT}>
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
      </div>
    </SignedInShell>
  );
}
