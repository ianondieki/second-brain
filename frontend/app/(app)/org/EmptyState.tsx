import Link from "next/link";

import { buttonClass, standaloneLinkClass } from "@/components/ui/Button";

/**
 * An empty or closed state: exactly one sentence and one action (docs/spec/07 item 4, AC-UX-5). `primary` makes the
 * action the screen's one primary button (for example "Turn on two-step sign-in" when nothing else can be done).
 */
export function EmptyState({
  sentence,
  action,
  href,
  primary = false,
}: {
  sentence: string;
  action: string;
  href: string;
  primary?: boolean;
}) {
  return (
    <div data-empty-state="" className="flex flex-col items-start gap-3 border-t border-line pt-6">
      <p className="max-w-[60ch] text-ink">{sentence}</p>
      {primary ? (
        <Link href={href} data-primary="" className={buttonClass("primary", "no-underline")}>
          {action}
        </Link>
      ) : (
        <Link href={href} className={standaloneLinkClass}>
          {action}
        </Link>
      )}
    </div>
  );
}
