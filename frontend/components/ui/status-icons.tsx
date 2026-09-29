import type { SVGProps } from "react";

// The icons client components use (status in alerts and fields, the confidential mark), apart from the rest of the
// set (components/ui/icons.tsx re-exports them): a client component that imports an icon ships its whole module, so
// the navigation and status icons that only server components draw stay out of the browser's bundles.

export type IconProps = SVGProps<SVGSVGElement>;

export function Icon({ children, ...props }: IconProps) {
  return (
    <svg
      width="20"
      height="20"
      viewBox="0 0 20 20"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.75"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
      {...props}
    >
      {children}
    </svg>
  );
}

export function AlertIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <circle cx="10" cy="10" r="7.5" />
      <path d="M10 6.25v4.5" />
      <path d="M10 13.6v.05" strokeWidth="2.25" />
    </Icon>
  );
}

export function CheckIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <circle cx="10" cy="10" r="7.5" />
      <path d="m6.75 10.25 2.25 2.25 4.25-4.75" />
    </Icon>
  );
}

export function InfoIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <circle cx="10" cy="10" r="7.5" />
      <path d="M10 9.25v4.5" />
      <path d="M10 6.4v.05" strokeWidth="2.25" />
    </Icon>
  );
}

/** Confidential (Tier 2): a padlock. */
export function LockIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <rect x="4.25" y="8.75" width="11.5" height="8.5" rx="1.5" />
      <path d="M6.75 8.75V6.5a3.25 3.25 0 0 1 6.5 0v2.25" />
    </Icon>
  );
}

/** Waiting (held for review, timestamp pending): a clock. */
export function ClockIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <circle cx="10" cy="10" r="7.5" />
      <path d="M10 6v4.25l2.75 1.75" />
    </Icon>
  );
}

/** Sent to an organisation (a pitch that reached it): a paper plane. */
export function SendIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="M16.75 3.25 8.5 11.5" />
      <path d="M16.75 3.25 11.5 16.75 8.5 11.5 3.25 8.5Z" />
    </Icon>
  );
}
