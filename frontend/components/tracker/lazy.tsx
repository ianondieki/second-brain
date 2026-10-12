"use client";

import { useRouter } from "next/navigation";
import { lazy, Suspense, useId, useState, type ComponentProps, type ComponentType } from "react";

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

// The P27 parts behind a button (REQ-ENG-15, REQ-PROV-06, REQ-DEV-04): the organisation's Team sheet and its
// prior-knowledge declaration, and the developer's dismissal of the IP note. The server draws the line and the
// button's words; the part's chunk is fetched when the pointer reaches the button or it takes focus, and drawn when it
// is pressed (pressed again, drawn anew). Closing gives focus back to the button and refreshes the tracker when
// something changed (a part that removes its own button moves focus itself: provenance/focus-line.ts).
const PARTS = {
  team: () => import("@/components/team/TeamSheet").then((m) => m.TeamSheet),
  declaration: () => import("@/components/provenance/DeclarationSheet").then((m) => m.DeclarationSheet),
  nudge: () => import("./NudgeDismiss").then((m) => m.NudgeDismiss),
};
type Parts = typeof PARTS;
type PartName = keyof Parts;
type Close = { onClose: (changed: boolean) => void };
export type PartProps<K extends PartName> = Omit<ComponentProps<Awaited<ReturnType<Parts[K]>>>, "onClose">;
const CHUNKS = { team: failSafe(PARTS.team), declaration: failSafe(PARTS.declaration), nudge: failSafe(PARTS.nudge) };

export function PartButton<K extends PartName>({
  part,
  label,
  className,
  props,
}: {
  part: K;
  label: string;
  className?: string;
  props: PartProps<K>;
}) {
  const [shown, show] = useState(0);
  const router = useRouter();
  const id = useId();
  const Part = CHUNKS[part] as unknown as ComponentType<PartProps<K> & Close>;
  const prefetch = () => void PARTS[part]().catch(() => undefined);
  function close(changed: boolean) {
    show(0);
    document.getElementById(id)?.focus();
    if (changed) router.refresh();
  }
  return (
    <>
      <button
        id={id}
        type="button"
        data-opens={part}
        className={className}
        onClick={() => show((n) => n + 1)}
        onPointerEnter={prefetch}
        onFocus={prefetch}
      >
        {label}
      </button>
      {shown ? (
        <Suspense fallback={null}>
          <Part key={shown} {...props} onClose={close} />
        </Suspense>
      ) : null}
    </>
  );
}
