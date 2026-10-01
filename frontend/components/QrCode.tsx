const QUIET_ZONE = 4; // modules of white around the symbol (ISO/IEC 18004)

/** Draws a QR matrix (true = dark module) as one SVG path: crisp at any size, no canvas, no images. */
export function QrCode({ matrix, label, className = "size-52" }: { matrix: boolean[][]; label: string; className?: string }) {
  const size = matrix.length + QUIET_ZONE * 2;
  let d = "";
  matrix.forEach((row, y) => {
    row.forEach((dark, x) => {
      if (dark) d += `M${x + QUIET_ZONE} ${y + QUIET_ZONE}h1v1h-1z`;
    });
  });
  return (
    <svg
      role="img"
      aria-label={label}
      viewBox={`0 0 ${size} ${size}`}
      shapeRendering="crispEdges"
      className={`block border border-line bg-white ${className}`}
    >
      <rect width={size} height={size} fill="#ffffff" />
      {/* Always dark on the white tile: a scanner needs the contrast in dark mode too (ux-reviewer P18 round 1). */}
      <path d={d} fill="#1a1916" />
    </svg>
  );
}
