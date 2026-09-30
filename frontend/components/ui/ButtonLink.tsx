import Link from "next/link";
import type { ComponentProps } from "react";

import { buttonClass, primaryMark, type ButtonVariant } from "./Button";
import { cn } from "./cn";
import { LinkPending } from "./LinkPending";

// Its own module, so client components that only need <Button> do not bundle next/link (about 4 KB gzipped).

export interface ButtonLinkProps extends ComponentProps<typeof Link> {
  variant?: ButtonVariant;
}

/**
 * A navigation that looks like a button (for example "Create an account" on the landing page). While its page is on
 * the way, the pending hint shows under the words, inside the button (in the text colour on a filled button), at a
 * fixed size, so nothing moves.
 */
export function ButtonLink({ variant = "secondary", className, children, ...rest }: ButtonLinkProps) {
  return (
    <Link className={buttonClass(variant, cn("relative", className))} {...primaryMark(variant)} {...rest}>
      {children}
      <LinkPending
        tone={variant === "primary" ? "current" : "accent"}
        className="absolute bottom-1.5 left-1/2 -translate-x-1/2"
      />
    </Link>
  );
}
