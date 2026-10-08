import { AdminNav } from "@/components/AdminNav";
import { PortalLoading } from "@/components/loading/PortalLoading";

/** While the console reads (D-67, P25): the console's shell around skeletons shaped like the page (the role's own
 *  sections arrive with the page; until then the rail shows the staff admin's). */
export default function Loading() {
  return <PortalLoading homeHref="/admin" nav={<AdminNav role="admin" current="research" />} shape="table" />;
}
