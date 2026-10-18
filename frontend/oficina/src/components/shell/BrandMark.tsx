/** Marca de HACK 30X: «30X» sobre azul eléctrico, con un punto lima (la señal que se anticipa). */
export function BrandMark({ size = 36 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 40 40" aria-hidden="true" focusable="false">
      <rect width="40" height="40" rx="10" fill="#3d7bff" />
      <text
        x="19"
        y="25.5"
        textAnchor="middle"
        fill="#ffffff"
        fontFamily="Geist Variable, Geist, system-ui, sans-serif"
        fontSize="15"
        fontWeight="700"
        letterSpacing="-0.5"
      >
        30X
      </text>
      <circle cx="32.5" cy="8" r="3" fill="#c6f432" />
    </svg>
  );
}
