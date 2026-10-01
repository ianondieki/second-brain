import { cn } from "./cn";

/**
 * The kanga-cut lattice band (D-52: the one East African signature): a 6 px two-tone edge on the top bar, the
 * landing hero's frame, the certificate sheet and empty-state art. Decorative, never behind text.
 */
export function Lattice({ className }: { className?: string }) {
  return <span aria-hidden="true" data-lattice="" className={cn("lattice-band block w-full", className)} />;
}
