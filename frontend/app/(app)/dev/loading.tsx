import { Skeleton } from "@/components/ui/Skeleton";

import { DevLoading } from "./DevLoading";

/** While the screen loads (P25): its shape in skeleton blocks inside the shell. */
export default function Loading() {
  return (
    <DevLoading current="home">
      <div className="max-w-4xl">
        <Skeleton className="h-60 w-full rounded-[1.5rem] sm:h-[16.5rem]" />
        <div className="mt-8 grid grid-cols-2 gap-3 sm:gap-4 lg:mt-10 lg:grid-cols-4">
          {[0, 1, 2, 3].map((i) => (
            <Skeleton key={i} className="h-28 rounded-panel" />
          ))}
        </div>
        <Skeleton className="mt-12 h-6 w-48" />
        <Skeleton className="mt-4 h-36 w-full rounded-panel" />
      </div>
    </DevLoading>
  );
}
