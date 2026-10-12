import { DAY, splitLeft } from "./clock-time";

export interface ClockFiguresProps {
  /** The instant the window closes (the API's `due_at`). */
  until: string;
  /** The app clock's instant when the page was drawn (the API's X-App-Now). */
  now: string;
  /** Said instead of the figures once `until` is reached (the screen's own word, "Overdue"). */
  labelWhenPast: string;
  /** "warm": the step is the viewer's, so under 24 hours the figures take the saffron "your turn" look. */
  tone?: "neutral" | "warm";
  /**
   * The clock's messages as written, from its largest unit down: days, hours, minutes. Each tags a figure as
   * <f>{days}</f> (or {hours}, {minutes}) and a unit word as <u>…</u>; the text between groups is the language's own.
   * Without them the clock is a sentence instead (`frame`).
   */
  formats?: readonly [string, string, string];
  /**
   * A sentence clock (no figures): the sentence around the time left with its {time} slot ("in {time}"), the time
   * left said in the language's own unit words ("in 6 days 14 hours 23 minutes"). Used when `formats` is not given.
   */
  frame?: string;
  /** The full instant in words (Nairobi time), the <time>'s title. */
  title: string;
  /** The page's locale: the duration in words ("6 days 14 hours 23 minutes") comes from Intl in this language. */
  locale: string;
  className?: string;
}

// A figure, a unit word, or the text between them, in a clock message. ClockTicker.tsx's script reads them the same way;
// exported for the catalogues' shape test (locales/clock-messages.test.ts).
export const PARTS = /<f>\{(days|hours|minutes)\}<\/f>|<u>([^<]*)<\/u>|([^<]+)/g;

/** Text for HTML (an element's text or an attribute's value in double quotes). */
function html(text: string): string {
  return text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/"/g, "&quot;");
}

/** The duration in words for a screen reader (Intl's long units in the page's language: "siku 6 saa 14 dakika 23"). */
function spoken(locale: string, d: number, h: number, m: number): string[] {
  // Day, hour and minute are sanctioned units (ECMA-402) in every browser the browserslist names: no fallback.
  const unit = (value: number, kind: "day" | "hour" | "minute") =>
    new Intl.NumberFormat(locale, { style: "unit", unit: kind, unitDisplay: "long" }).format(value);
  const parts = [];
  if (d) parts.push(unit(d, "day"));
  if (d || h) parts.push(unit(h, "hour"));
  parts.push(unit(m, "minute"));
  return parts;
}

/** A clock message filled: each figure and unit word in its own span, in the message's order. */
function figuresHtml(format: string, d: number, h: number, m: number): string {
  const values = { days: d, hours: h, minutes: m };
  return [...format.matchAll(PARTS)]
    .map(([, figure, unit, text]) =>
      figure
        ? `<span data-figure="">${values[figure as keyof typeof values]}</span>`
        : unit !== undefined
          ? `<span data-unit="">${html(unit)}</span>`
          : `<span data-gap="">${html(text)}</span>`,
    )
    .join("");
}

/**
 * A deadline clock's figures (P26), drawn on the server and kept by the page's ticker (ClockTicker.tsx; P27): days,
 * hours and minutes as figures (leading units that are zero left out), each with its unit word where the language's
 * message puts it, in one <time> whose figures read as the duration ("6 d 14 h 23 min", "siku 6 saa 14 dak 23") beside
 * its words for screen readers; or, given a `frame` instead of `formats`, the time left as words in a sentence. No live
 * region. The look is the caller's className, keyed on data-clock, data-figure, data-unit and data-gap; the figures sit
 * under data-clock-figures, aria-hidden.
 *
 * Everything the ticker needs is on the element: the instants (data-until, data-now), the tone, the locale, the word
 * for "past" and the three messages, so its script carries no words of any language. The inside is HTML the ticker
 * rewrites on the minute: React sets it from text escaped here (dangerouslySetInnerHTML) and leaves it alone while that
 * HTML is unchanged, so a tick before or after hydration never makes React and the ticker disagree. A refresh of the
 * page that draws the clock again sets the new HTML and data-now, and the ticker starts again from those.
 */
export function ClockFigures({
  until,
  now,
  labelWhenPast,
  tone,
  formats,
  frame = "{time}",
  title,
  className,
  locale,
}: ClockFiguresProps) {
  const left = Date.parse(until) - Date.parse(now);
  const { d, h, m } = splitLeft(left);
  let inside = html(labelWhenPast);
  if (left > 0) {
    const time = `<time datetime="P${d}DT${h}H${m}M" title="${html(title)}">`;
    const units = spoken(locale, d, h, m);
    if (formats) {
      // Leading units that are zero are not drawn ("14 h 23 min", "23 min"): the message for the largest unit left.
      const figures = figuresHtml(formats[d ? 0 : h ? 1 : 2], d, h, m);
      // The duration in words for screen readers; the figures beside it are its picture (a letter "d" read out would
      // not be).
      inside = `${time}<span class="sr-only">${html(units.join(" "))}</span><span data-clock-figures="" aria-hidden="true">${figures}</span></time>`;
    } else {
      const [before, after = ""] = frame.split("{time}");
      // The words wrap between units, never inside one ("15 days", "siku 15" each held by no-break spaces), as the
      // ticker writes them.
      const words = units.map((unit) => unit.replace(/ /g, "\u00a0")).join(" ");
      inside = `${html(before)}${time}${html(words)}</time>${html(after)}`;
    }
  }
  return (
    <span
      data-clock={left > 0 ? (tone === "warm" && left < DAY ? "warm" : "open") : "past"}
      data-until={until}
      data-now={now}
      data-tone={tone === "warm" ? "warm" : undefined}
      data-locale={locale}
      data-past={labelWhenPast}
      data-format-days={formats?.[0]}
      data-format-hours={formats?.[1]}
      data-format-minutes={formats?.[2]}
      className={className}
      // The ticker may have moved the figures and data-clock on before React hydrates them (attributes: React does not
      // patch them; the inside is dangerouslySetInnerHTML).
      suppressHydrationWarning
      dangerouslySetInnerHTML={{ __html: inside }}
    />
  );
}
