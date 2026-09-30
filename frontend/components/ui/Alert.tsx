import type { ReactNode, Ref } from "react";

import { cn } from "./cn";
import { noticeBox, noticeIconTone, noticeTone } from "./notice";
import { AlertIcon, CheckIcon, InfoIcon } from "./status-icons";

export type AlertTone = "error" | "info" | "ok";

export interface AlertProps {
  tone?: AlertTone;
  children: ReactNode;
  className?: string;
  ref?: Ref<HTMLDivElement>;
}

/**
 * A notice with an icon and words that appears because something happened (a refusal, a saved change). Errors use
 * role="alert" (announced at once); info and success use role="status" (announced politely). A notice that is part
 * of the page from the start is a Callout, with the same tones.
 */
export function Alert({ tone = "error", children, className, ref }: AlertProps) {
  const Icon = tone === "error" ? AlertIcon : tone === "ok" ? CheckIcon : InfoIcon;
  return (
    <div
      ref={ref}
      tabIndex={-1}
      role={tone === "error" ? "alert" : "status"}
      className={cn(noticeBox, noticeTone[tone], className)}
    >
      <Icon className={cn("mt-0.5 size-5 shrink-0", noticeIconTone[tone])} />
      <div className="min-w-0">{children}</div>
    </div>
  );
}
