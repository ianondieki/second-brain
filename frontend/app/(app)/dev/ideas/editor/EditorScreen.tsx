import Link from "next/link";
import { redirect } from "next/navigation";
import { getTranslations } from "next-intl/server";

import { DevNav } from "@/components/DevNav";
import { ClientStrings } from "@/components/ClientStrings";
import { SignedInShell } from "@/components/SignedInShell";
import { standaloneLinkClass } from "@/components/ui/Button";
import { requireMe } from "@/lib/api/server";
import { clientStrings } from "@/lib/i18n/client-strings";
import { homeFor } from "@/lib/auth/routing";

import { editorOptions, myIdea } from "../data";
import {
  BASE_PATH,
  ideaHref,
  type Step,
} from "../ideas";
import { editableVersion, stateFromVersion } from "../versions";
import { Editor } from "./Editor";

/**
 * The editor's page for a new idea (id null) or one of yours: developers only; a hidden idea cannot change, so it
 * opens its own page instead. Everything the steps need is fetched here, on the server.
 */
export async function EditorScreen({ id, step }: { id: string | null; step: Step }) {
  const me = await requireMe();
  const home = homeFor(me.side);
  if (home !== "/dev") redirect(home);
  const t = await getTranslations("ideaEditor");
  const ideas = await getTranslations("ideas");
  const [idea, options] = await Promise.all([id ? myIdea(id) : Promise.resolve(null), editorOptions()]);

  if (id && !idea) {
    return (
      <SignedInShell homeHref={home} nav={<DevNav current="ideas" />}>
        <h1 className="text-xl text-ink lg:text-2xl">{t("pageTitleEdit")}</h1>
        <div data-empty-state="" className="mt-6 border-t border-line pt-6">
          <p className="text-ink">{ideas("notFound")}</p>
          <Link href={BASE_PATH} className={standaloneLinkClass}>
            {ideas("back")}
          </Link>
        </div>
      </SignedInShell>
    );
  }
  if (idea && (idea.status === "hidden" || idea.status === "archived")) redirect(ideaHref(idea.id));

  const version = idea ? editableVersion(idea) : null;
  return (
    <SignedInShell homeHref={home} nav={<DevNav current="ideas" />}>
      <p className="-mt-2 mb-4">
        <Link href={idea ? ideaHref(idea.id) : BASE_PATH} className={standaloneLinkClass}>
          {idea ? t("backToIdea") : ideas("back")}
        </Link>
      </p>
      <ClientStrings strings={await clientStrings(["ideaEditor", "ideaFields"])}>
        <Editor
          id={idea?.id ?? null}
          hasDraft={idea?.draft != null}
          initial={stateFromVersion(version)}
          attachments={version?.confidential.attachments ?? []}
          step={step}
          niches={options.niches}
          counties={options.counties}
          attestations={options.attestations}
          problems={options.problems}
        />
      </ClientStrings>
    </SignedInShell>
  );
}
