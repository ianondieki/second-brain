/** Joins class names, skipping falsy values (a dependency-free stand-in for clsx). */
export function cn(...parts: Array<string | false | null | undefined>): string {
  return parts.filter(Boolean).join(" ");
}
