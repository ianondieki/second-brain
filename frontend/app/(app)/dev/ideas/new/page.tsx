import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";

import { EditorScreen } from "../editor/EditorScreen";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("ideaEditor");
  return { title: t("pageTitleNew") };
}

/** A new idea (REQ-PROP-01): nothing is created until the first save, a moment after you start typing. */
export default async function NewIdeaPage() {
  return <EditorScreen id={null} step={1} />;
}
