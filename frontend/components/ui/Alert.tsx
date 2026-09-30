import type { ReactNode, Ref } from "react";

import { cn } from "./cn";
import { AlertIcon, CheckIcon, InfoIcon } from "./status-icons";

export type AlertTone = "error" | "info" | "ok";

const tones: Record<AlertTone, string> = {
  error: "border-error-line bg-error-wash",
  info: "border-accent-line bg-jacaranda-wash",
  ok: "border-ok-line bg-ok-wash",
};

const iconTone: Record<AlertTone, string> = { error: "text-error", info: "text-jacaranda", ok: "text-ok" };

export interface AlertProps {
  tone?: AlertTone;
  children: ReactNode;
  className?: string;
  ref?: Ref<HTMLDivElement>;
}

/**
 * A notice with an icon and words. Errors use role="alert" (announced at once); info and success use
 * role="status" (announced politely).
 */
export function Alert({ tone = "error", children, className, ref }: AlertProps) {
  const Icon = tone === "error" ? AlertIcon : tone === "ok" ? CheckIcon : InfoIcon;
  return (
    <div
      ref={ref}
      tabIndex={-1}
      role={tone === "error" ? "alert" : "status"}
      className={cn("flex items-start gap-3 rounded-control border px-4 py-3 text-ink", tones[tone], className)}
    >
      <Icon className={cn("mt-0.5 size-5 shrink-0", iconTone[tone])} />
      <div className="min-w-0">{children}</div>
    </div>
  );
}
