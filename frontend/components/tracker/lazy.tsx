"use client";

import { lazy, Suspense, type ComponentProps, type ComponentType } from "react";

import { useStrings } from "@/components/ClientStrings";
import { Button } from "@/components/ui/Button";

// The tracker's rarely shown client parts (P23-3; docs/spec/07 item 5: the tracker route sits at its JS budget), each
// in its own chunk that loads only on a page that draws it: the developer's Tier-2 share (until it is shared), the
// named contact's reveal and the fresh-code form a signature or payment may ask for. The server still renders the
// first two in the page's HTML. No code split may fail into the route's error boundary (PROGRESS.md, P16-C1): a part
// whose chunk cannot load (offline, a new deploy) says so in one sentence with one way on, and the rest of the
// tracker, its primary action included, stays.

/** In place of a part that did not load: one sentence and a reload (nothing was sent: the part never ran). */
export function PartFailed() {
  const t = useStrings("trackerActions");
  return (
    <div role="alert" data-part-failed="" className="flex flex-col items-start gap-2">
      <p className="text-ink">{t("partFailed")}</p>
      <Button variant="secondary" onClick={() => location.reload()}>
        {t("partReload")}
      </Button>
    </div>
  );
}

/** React.lazy whose failed import settles into PartFailed instead of throwing. */
function failSafe<P extends object>(load: () => Promise<ComponentType<P>>) {
  return lazy(() =>
    load().then(
      (part) => ({ default: part }),
      () => ({ default: PartFailed as ComponentType<P> }),
    ),
  );
}

const ShareTier2Chunk = failSafe(() => import("./ShareTier2").then((m) => m.ShareTier2));
const ContactRevealChunk = failSafe(() => import("./ContactReveal").then((m) => m.ContactReveal));
/** Actions draws it inside its own Suspense, with its "Working…" fallback. */
export const LazyStepUp = failSafe(() => import("./StepUp").then((m) => m.StepUp));

export function LazyShareTier2(props: ComponentProps<typeof ShareTier2Chunk>) {
  return (
    <Suspense fallback={null}>
      <ShareTier2Chunk {...props} />
    </Suspense>
  );
}

export function LazyContactReveal(props: ComponentProps<typeof ContactRevealChunk>) {
  return (
    <Suspense fallback={null}>
      <ContactRevealChunk {...props} />
    </Suspense>
  );
}
