import { LogoMark } from "../brand/Logo";
import { DIRECTION, type DirectionKey, type Theme } from "../directions";
import { EMAIL, PLACEHOLDER_NAME } from "../fixtures";

/**
 * The branded EM7 daily reminder as it would render in a mail client: a table layout with inline styles and hex
 * values from the direction's palette (mail clients read no CSS variables), 600 px wide, responsive by fluid widths.
 * A preview of the step-3 template (backend reminders/templates/em7.html.j2); the plain-text part stays as it is.
 */
export function EmailScreen({ direction, theme }: { direction: DirectionKey; theme: Theme }) {
  const d = DIRECTION[direction];
  const p = d[theme];
  const display = `'${d.fonts.display}', Georgia, serif`;
  const text = `'${d.fonts.text}', -apple-system, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif`;
  return (
    <div style={{ background: p.paper, padding: "32px 16px", fontFamily: text, color: p.ink }}>
      <p style={{ maxWidth: 600, margin: "0 auto 12px", fontSize: 13, color: p.inkSoft }}>
        Subject: {EMAIL.subject}
      </p>
      <table role="presentation" cellPadding={0} cellSpacing={0} style={{ width: "100%", maxWidth: 600, margin: "0 auto", background: p.field, border: `1px solid ${p.line}`, borderRadius: d.radius.panel, overflow: "hidden" }}>
        <tbody>
          <tr>
            <td data-lattice="" style={{ padding: "20px 28px", borderBottom: `1px solid ${p.line}` }}>
              <span style={{ display: "inline-flex", alignItems: "center", gap: 10, fontFamily: display, fontWeight: d.type.displayWeight, fontSize: 20, letterSpacing: d.type.displayTracking }}>
                <LogoMark direction={direction} size={24} />
                {PLACEHOLDER_NAME}
              </span>
            </td>
          </tr>
          <tr>
            <td style={{ padding: "28px 28px 8px" }}>
              <h1 style={{ margin: 0, fontFamily: display, fontWeight: d.type.displayWeight, fontSize: 24, lineHeight: 1.25, letterSpacing: d.type.displayTracking }}>
                {EMAIL.headline}
              </h1>
            </td>
          </tr>
          {EMAIL.sections.map((section) => (
            <tr key={section.title}>
              <td style={{ padding: "16px 28px 0" }}>
                <h2 style={{ margin: "0 0 8px", fontFamily: display, fontWeight: d.type.displayWeight, fontSize: 17 }}>{section.title}</h2>
                <table role="presentation" cellPadding={0} cellSpacing={0} style={{ width: "100%" }}>
                  <tbody>
                    {section.lines.map((line) => (
                      <tr key={line}>
                        <td style={{ padding: "10px 0", borderTop: `1px solid ${p.line}`, fontSize: 15, lineHeight: 1.5 }}>{line}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </td>
            </tr>
          ))}
          <tr>
            <td style={{ padding: "24px 28px 0" }}>
              <p style={{ margin: 0, padding: "14px 16px", background: p.accentWash, borderRadius: d.radius.control, fontSize: 15, lineHeight: 1.5 }}>{EMAIL.nextStep}</p>
            </td>
          </tr>
          <tr>
            <td style={{ padding: "24px 28px 32px" }}>
              <a href="#" style={{ display: "inline-block", background: p.accent, color: p.onAccent, textDecoration: "none", padding: "14px 22px", borderRadius: d.radius.control, fontSize: 15, fontWeight: 600 }}>
                {EMAIL.cta}
              </a>
            </td>
          </tr>
        </tbody>
      </table>
      <p style={{ maxWidth: 600, margin: "16px auto 0", fontSize: 12, lineHeight: 1.5, color: p.inkSoft }}>
        {EMAIL.footer}
        <br />
        <a href="#" style={{ color: p.inkSoft }}>Manage notifications</a> · <a href="#" style={{ color: p.inkSoft }}>Help</a> · Seeded example
      </p>
    </div>
  );
}
