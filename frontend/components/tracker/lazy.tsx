"use client";

import { useRouter } from "next/navigation";
import {
  lazy,
  Suspense,
  useId,
  useRef,
  useState,
  type ComponentProps,
  type ComponentType,
  type ReactNode,
} from "react";

import { useStrings } from "@/components/ClientStrings";
import { Button } from "@/components/ui/Button";
import { api } from "@/lib/api/client";

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

// The organisation's Team sheet and prior-knowledge declaration (P27: REQ-ENG-15, REQ-PROV-06): the server draws the
// line and its opener's words; the sheet's chunk is fetched when the pointer reaches the opener or it takes focus,
// and drawn when it is pressed. Closing gives focus back to the opener (or, once the opener is gone because the
// change removed it, to the element `after` names) and refreshes the tracker when something changed.
const loadTeam = () => import("@/components/team/TeamSheet");
const loadDeclaration = () => import("@/components/provenance/DeclarationSheet");
const TeamSheetChunk = failSafe(() => loadTeam().then((m) => m.TeamSheet));
const DeclarationSheetChunk = failSafe(() => loadDeclaration().then((m) => m.DeclarationSheet));

interface OpenerProps {
  label: string;
  className?: string;
  /** The id to focus when the change removed the opener itself (the declaration's line). */
  after?: string;
}

function Opener({
  label,
  className,
  after,
  name,
  load,
  sheet,
}: OpenerProps & {
  name: string;
  load: () => Promise<unknown>;
  sheet: (onClose: (changed: boolean) => void) => ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const router = useRouter();
  const id = useId();
  const prefetch = () => void load().catch(() => undefined);
  function close(changed: boolean) {
    setOpen(false);
    document.getElementById(id)?.focus();
    if (!changed) return;
    router.refresh();
    if (after) setTimeout(() => document.getElementById(id) || document.getElementById(after)?.focus(), 1500);
  }
  return (
    <>
      <button
        id={id}
        type="button"
        data-opens={name}
        className={className}
        onClick={() => setOpen(true)}
        onPointerEnter={prefetch}
        onFocus={prefetch}
      >
        {label}
      </button>
      {open ? <Suspense fallback={null}>{sheet(close)}</Suspense> : null}
    </>
  );
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type SheetProps<C extends ComponentType<any>> = Omit<ComponentProps<C>, "onClose">;

export function TeamSheetButton({
  label,
  className,
  after,
  ...props
}: OpenerProps & SheetProps<typeof TeamSheetChunk>) {
  return (
    <Opener
      label={label}
      className={className}
      after={after}
      name="team"
      load={loadTeam}
      sheet={(onClose) => <TeamSheetChunk {...props} onClose={onClose} />}
    />
  );
}

export function DeclarationSheetButton({
  label,
  className,
  after,
  ...props
}: OpenerProps & SheetProps<typeof DeclarationSheetChunk>) {
  return (
    <Opener
      label={label}
      className={className}
      after={after}
      name="declaration"
      load={loadDeclaration}
      sheet={(onClose) => <DeclarationSheetChunk {...props} onClose={onClose} />}
    />
  );
}

/**
 * The developer's IP note's Dismiss (REQ-DEV-04): POST /api/me/profile/ip-nudge/dismiss, then the note is hidden
 * (and gone from the refreshed tracker); focus moves to the actions' heading. A refusal says so beside the button.
 */
export function DismissNudge({ label, failed }: { label: string; failed: string }) {
  const router = useRouter();
  const [state, setState] = useState<"idle" | "busy" | "failed">("idle");
  const box = useRef<HTMLSpanElement>(null);
  async function dismiss() {
    if (state === "busy") return;
    setState("busy");
    const ok = await api.POST("/api/me/profile/ip-nudge/dismiss").then(
      ({ response }) => response.ok,
      () => false,
    );
    if (!ok) return setState("failed");
    box.current?.closest("[data-ip-nudge]")?.setAttribute("hidden", "");
    document.getElementById("actions-heading")?.focus();
    router.refresh();
  }
  return (
    <span ref={box} className="flex flex-col items-start gap-2">
      {state === "failed" ? (
        <span role="alert" className="text-sm font-medium text-error">
          {failed}
        </span>
      ) : null}
      <Button variant="secondary" busy={state === "busy"} onClick={() => void dismiss()} data-dismiss-nudge="">
        {label}
      </Button>
    </span>
  );
}
