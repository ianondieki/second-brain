const QUIET_ZONE = 4; // modules of white around the symbol (ISO/IEC 18004)

/** Draws a QR matrix (true = dark module) as one SVG path: crisp at any size, no canvas, no images. */
export function QrCode({ matrix, label }: { matrix: boolean[][]; label: string }) {
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
      className="block size-52 border border-line bg-white"
    >
      <rect width={size} height={size} fill="#ffffff" />
      <path d={d} fill="var(--ink)" />
    </svg>
  );
}
