import { DevLoading, TrackerSkeleton } from "../../DevLoading";

/** While the screen loads (P25): its shape in skeleton blocks inside the shell. */
export default function Loading() {
  return (
    <DevLoading current="engagements">
      <TrackerSkeleton />
    </DevLoading>
  );
}
