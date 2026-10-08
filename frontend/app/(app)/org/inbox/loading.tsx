import { LoadingNav } from "@/components/loading/LoadingNav";
import { PortalLoading } from "@/components/loading/PortalLoading";

/** While the page reads (D-67, P25): the organisation shell around skeletons shaped like it. */
export default function Loading() {
  return <PortalLoading homeHref="/org" nav={<LoadingNav portal="org" current="inbox" />} shape="cards" tabs={true} action={false} />;
}
