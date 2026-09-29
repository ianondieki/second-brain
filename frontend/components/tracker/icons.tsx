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
