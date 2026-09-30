import { Badge } from "@/components/ui/Badge";
import { InfoIcon } from "@/components/ui/status-icons";

/** The D-44 label beside prices while plans.yaml holds placeholders: a neutral Badge, an icon and words. */
export function SamplePrices({ label }: { label: string }) {
  return (
    <Badge data-sample-prices="" tone="neutral" icon={<InfoIcon />}>
      {label}
    </Badge>
  );
}
