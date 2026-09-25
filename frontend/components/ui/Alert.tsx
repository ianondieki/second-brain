import type { ReactNode, Ref } from "react";

import { cn } from "./cn";
import { AlertIcon, CheckIcon, InfoIcon } from "./icons";

export type AlertTone = "error" | "info" | "ok";

const tones: Record<AlertTone, string> = {
  error: "border-[color-mix(in_oklab,var(--error)_45%,var(--paper))] bg-[color-mix(in_oklab,var(--error)_7%,var(--field))]",
  info: "border-[color-mix(in_oklab,var(--jacaranda)_35%,var(--paper))] bg-jacaranda-wash",
  ok: "border-[color-mix(in_oklab,var(--ok)_45%,var(--paper))] bg-[color-mix(in_oklab,var(--ok)_7%,var(--field))]",
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
