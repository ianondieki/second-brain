/** The words of the preview, already formatted (the server's for the first paint, the live preview's after an edit). */
export interface BriefPreviewWords {
  heading: string;
  title: string;
  niche: string | null;
  place: string;
  postedBy: string;
  statement: string;
  budget: string;
  deadline: string;
  note: string;
}

/**
 * How the Brief will read on Discover (D-67, P25): the card a developer meets, with the title, the niche and place,
 * "Posted by" the organisation, the statement (three lines), and the budget band and deadline. Decorative for
 * assistive technology apart from its heading: the form's own fields carry every word, so the preview is not read
 * twice. No hooks and no client code: the page draws it for the first paint, BriefPreview (loaded on the first edit)
 * draws it live. No photograph (the browser would fetch one as the niche changes).
 */
export function BriefPreviewView({ words }: { words: BriefPreviewWords }) {
  return (
    <section aria-labelledby="brief-preview-heading" className="brief-preview" data-brief-preview="">
      <h2 id="brief-preview-heading" className="page-eyebrow">
        {words.heading}
      </h2>
      <div aria-hidden="true" className="brief-preview-card">
        <div className="niche-band niche-band-lattice h-10 rounded-none" />
        <div className="flex flex-col gap-2 p-4">
          <p className="text-[1.0625rem] leading-snug font-semibold [overflow-wrap:anywhere] text-ink" data-preview="title">
            {words.title}
          </p>
          <p className="flex flex-wrap gap-x-4 text-sm text-ink-soft">
            {words.niche ? <span>{words.niche}</span> : null}
            <span>{words.place}</span>
          </p>
          <p className="text-sm font-medium text-ink">{words.postedBy}</p>
          <p className="line-clamp-3 [overflow-wrap:anywhere] text-ink-soft" data-preview="statement">
            {words.statement}
          </p>
          <p className="flex flex-wrap gap-x-4 gap-y-1 text-sm font-semibold text-ink tabular-nums">
            <span>{words.budget}</span>
            <span>{words.deadline}</span>
          </p>
        </div>
      </div>
      <p className="mt-2 text-sm text-ink-soft">{words.note}</p>
    </section>
  );
}
