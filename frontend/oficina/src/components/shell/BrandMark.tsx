/** Marca de HACK 30X: tres anillos de detección y una señal. Estática: no simula actividad. */
export function BrandMark({ size = 34 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 40 40" aria-hidden="true" focusable="false">
      <rect x="0.5" y="0.5" width="39" height="39" rx="10" fill="#0f151d" stroke="#31404f" />
      <circle cx="20" cy="20" r="13" fill="none" stroke="#31404f" />
      <circle cx="20" cy="20" r="8" fill="none" stroke="#31404f" />
      <path d="M20 20 L31 13" stroke="#c8f25a" strokeWidth="2" strokeLinecap="round" />
      <circle cx="27" cy="15.5" r="2.4" fill="#c8f25a" />
      <circle cx="20" cy="20" r="2" fill="#e7edf3" />
    </svg>
  );
}
