import Link from "next/link";
import type { ComponentProps } from "react";

import { buttonClass, primaryMark, type ButtonVariant } from "./Button";

// Its own module, so client components that only need <Button> do not bundle next/link (about 4 KB gzipped).

export interface ButtonLinkProps extends ComponentProps<typeof Link> {
  variant?: ButtonVariant;
}

/** A navigation that looks like a button (for example "Create an account" on the landing page). */
export function ButtonLink({ variant = "secondary", className, ...rest }: ButtonLinkProps) {
  return <Link className={buttonClass(variant, className)} {...primaryMark(variant)} {...rest} />;
}
