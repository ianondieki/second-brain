import { getTranslations } from "next-intl/server";

import { LoadingScreen } from "@/components/ui/LoadingScreen";

/** Shown while a page of this group renders on the server (Next's loading boundary). */
export default async function Loading() {
  const t = await getTranslations("app");
  return <LoadingScreen label={t("loading")} />;
}
