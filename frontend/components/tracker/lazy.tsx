"use client";

import { lazy, Suspense, type ComponentProps } from "react";

// The tracker's rarely shown client parts (P23-3; docs/spec/07 item 5: the tracker route sits at its JS budget), each
// in its own chunk that loads only on a page that draws it: the developer's Tier-2 share (until it is shared) and the
// named contact's reveal. The server still renders them in the page's HTML; their buttons work once the chunk arrives.

const ShareTier2Chunk = lazy(() => import("./ShareTier2").then((m) => ({ default: m.ShareTier2 })));
const ContactRevealChunk = lazy(() => import("./ContactReveal").then((m) => ({ default: m.ContactReveal })));

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
