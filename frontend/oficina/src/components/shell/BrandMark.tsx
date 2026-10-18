/** Marca de HACK 30X: insignia de canal roja con «30X», como los números de canal de las guías de TV. */
export function BrandMark({ size = 36, inverse = false }: { size?: number; inverse?: boolean }) {
  return (
    <svg width={size} height={size} viewBox="0 0 40 40" aria-hidden="true" focusable="false">
      <rect width="40" height="40" rx="3" fill={inverse ? "#ffffff" : "#d21f2b"} />
      <text
        x="20"
        y="27"
        textAnchor="middle"
        fill={inverse ? "#d21f2b" : "#ffffff"}
        fontFamily="Archivo Variable, Archivo, sans-serif"
        fontSize="17"
        fontWeight="800"
        style={{ fontStretch: "62%" }}
      >
        30X
      </text>
    </svg>
  );
}
