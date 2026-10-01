import { DevNav } from "@/components/DevNav";
import { SignedInShell } from "@/components/SignedInShell";
import { EngagementScreen } from "@/components/tracker/EngagementScreen";

import { DETAIL, ME } from "../fixtures";

/** The real tracker (components/tracker/EngagementScreen) on a fixture engagement: both parties owe the NDA. */
export function TrackerScreen() {
  return (
    <SignedInShell homeHref="/dev" nav={<DevNav current="engagements" />} wide>
      <EngagementScreen detail={DETAIL} me={ME} tab="tracker" doc={null} basePath="/dev/engagements" />
    </SignedInShell>
  );
}
