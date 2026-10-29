import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";

import { EditorScreen } from "../../editor/EditorScreen";
import { parseStep } from "../../routes";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("ideaEditor");
  return { title: t("pageTitleEdit") };
}

/** Edit one of your ideas (REQ-PROP-01); `?step=2` or `3` opens that step. Editing a published idea saves the next
 * version as a draft: the published one does not change until you publish again. */
export default async function EditIdeaPage({ params, searchParams }: PageProps<"/dev/ideas/[id]/edit">) {
  const [{ id }, query] = await Promise.all([params, searchParams]);
  return <EditorScreen id={id} step={parseStep(query.step)} />;
}
