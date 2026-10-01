import { HomeContent } from "@/app/(app)/dev/HomeContent";

import { HOME_ENGAGEMENTS, IDEAS, ME, RECOMMENDATIONS } from "../fixtures";

/** Developer Home as app/(app)/dev/page.tsx renders it, on fixture data (no API). */
export function HomeScreen() {
  return <HomeContent me={ME} engagements={HOME_ENGAGEMENTS} ideas={IDEAS} recommended={RECOMMENDATIONS} />;
}
