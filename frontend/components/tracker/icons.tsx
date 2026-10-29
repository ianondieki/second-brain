import { Icon, type IconProps } from "@/components/ui/status-icons";

/** Engagements: two arrows passing each other, the developer's side and the organisation's. */
export function EngagementsIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="M3.5 7h12.25" />
      <path d="m12.75 4 3 3-3 3" />
      <path d="M16.5 13H4.25" />
      <path d="m7.25 10-3 3 3 3" />
    </Icon>
  );
}

/** Messages: a speech bubble. */
export function MessageIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="M4.25 4.5h11.5a1.25 1.25 0 0 1 1.25 1.25v7.5a1.25 1.25 0 0 1-1.25 1.25H9l-3.5 2.75V14.5H4.25A1.25 1.25 0 0 1 3 13.25v-7.5A1.25 1.25 0 0 1 4.25 4.5z" />
    </Icon>
  );
}
