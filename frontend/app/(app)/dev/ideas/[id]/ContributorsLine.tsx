"use client";

import { useRouter } from "next/navigation";
import { useEffect, useRef, useState, useTransition } from "react";

import { useStrings } from "@/components/ClientStrings";
import { Alert } from "@/components/ui/Alert";
import { Button } from "@/components/ui/Button";
import { ConfirmDialog, openConfirm } from "@/components/ui/ConfirmDialog";
import { api, type ApiClient } from "@/lib/api/client";

export interface Credited {
  user_id: string;
  handle: string;
}

/** Removes one contributor's credit from the caller's idea (204); false when it did not happen. */
export async function removeContributor(proposalId: string, userId: string, client: ApiClient = api): Promise<boolean> {
  try {
    const { response } = await client.DELETE("/api/me/ideas/{proposal_id}/contributors/{user_id}", {
      params: { path: { proposal_id: proposalId, user_id: userId } },
    });
    return response.ok;
  } catch {
    return false;
  }
}

/**
 * "Contributors: …" on the owner's idea page (REQ-DEV-03; D-62 (a)), each handle with "Remove" behind a confirmation
 * (a removed credit cannot be added back). Once removed, a status line says so (it takes focus) and the page is read
 * again, so the certificate's line follows.
 */
export function ContributorsLine({
  ideaId,
  initial,
  remove = removeContributor,
}: {
  ideaId: string;
  initial: readonly Credited[];
  remove?: typeof removeContributor;
}) {
  const t = useStrings("ideaContributors");
  const router = useRouter();
  const [, startRefresh] = useTransition();
  const dialog = useRef<HTMLDialogElement>(null);
  const status = useRef<HTMLDivElement>(null);
  const [items, setItems] = useState(initial);
  const [target, setTarget] = useState<Credited | null>(null);
  const [state, setState] = useState<"idle" | "busy" | "failed">("idle");
  const [said, setSaid] = useState<{ text: string; n: number } | null>(null);
  const removed = useRef(false);

  useEffect(() => {
    if (target) openConfirm(dialog.current);
  }, [target]);
  useEffect(() => {
    if (said) status.current?.focus();
  }, [said]);

  async function confirm() {
    if (!target || state === "busy") return;
    setState("busy");
    const ok = await remove(ideaId, target.user_id);
    if (!ok) {
      setState("failed");
      return;
    }
    removed.current = true;
    dialog.current?.close();
  }

  return (
    <div className={items.length > 0 || said ? "mt-3 flex flex-col gap-3" : undefined}>
      {items.length > 0 ? (
        <p className="flex flex-wrap items-center gap-x-2 text-ink" data-contributors="">
          <span>{t("label")}</span>{" "}
          {items.map((item) => (
            <span key={item.user_id} className="inline-flex items-center gap-1" data-contributor={item.handle}>
              <span id={`contributor-${item.user_id}`} className="font-semibold">
                {item.handle}
              </span>
              <Button
                variant="link"
                className="text-sm"
                aria-haspopup="dialog"
                aria-describedby={`contributor-${item.user_id}`}
                onClick={() => {
                  setState("idle");
                  setTarget(item);
                }}
                data-remove-contributor=""
              >
                {t("remove")}
              </Button>
            </span>
          ))}
        </p>
      ) : null}
      {said ? (
        <Alert key={said.n} ref={status} tone="ok" className="max-w-2xl">
          {said.text}
        </Alert>
      ) : null}
      <ConfirmDialog
        ref={dialog}
        tone="danger"
        title={t("confirmTitle", { name: target?.handle ?? "" })}
        confirmLabel={t("confirm")}
        busyLabel={t("removing")}
        cancelLabel={t("cancel")}
        busy={state === "busy"}
        onConfirm={() => void confirm()}
        problem={state === "failed" ? <Alert>{t("failed")}</Alert> : null}
        onClose={() => {
          const gone = target;
          setTarget(null);
          setState("idle");
          if (gone && removed.current) {
            removed.current = false;
            setItems((now) => now.filter((item) => item.user_id !== gone.user_id));
            setSaid((now) => ({ text: t("removed", { name: gone.handle }), n: (now?.n ?? 0) + 1 }));
            startRefresh(() => router.refresh());
          }
        }}
      >
        <p>{t("confirmBody")}</p>
      </ConfirmDialog>
    </div>
  );
}
