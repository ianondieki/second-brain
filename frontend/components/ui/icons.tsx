import type { SVGProps } from "react";

// One authored icon set: 20 px grid, 1.75 stroke, round joins, currentColor. Icons are decorative: the words next
// to them carry the meaning (status = icon + text + colour, docs/spec/07 item 6).

type IconProps = SVGProps<SVGSVGElement>;

function Icon({ children, ...props }: IconProps) {
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

export function EyeIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="M1.75 10S4.75 4.5 10 4.5 18.25 10 18.25 10 15.25 15.5 10 15.5 1.75 10 1.75 10Z" />
      <circle cx="10" cy="10" r="2.5" />
    </Icon>
  );
}

export function EyeOffIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="M8.2 4.7A8 8 0 0 1 10 4.5c5.25 0 8.25 5.5 8.25 5.5a14 14 0 0 1-2.1 2.8" />
      <path d="M12.1 12.2a2.5 2.5 0 0 1-3.9-3.1" />
      <path d="M5.3 6.3C3 7.8 1.75 10 1.75 10S4.75 15.5 10 15.5a7.6 7.6 0 0 0 3.6-.9" />
      <path d="m2.5 2.5 15 15" />
    </Icon>
  );
}
