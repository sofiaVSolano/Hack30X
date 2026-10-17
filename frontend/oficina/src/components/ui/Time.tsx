import { formatDateTime, formatDay } from "@/lib/format";

/** Fecha y hora: texto local legible; el valor UTC original queda en `dateTime` y en `title`. */
export function Time({ value }: { value: string | null | undefined }) {
  if (!value) return <span className="faint">—</span>;
  return (
    <time dateTime={value} title={`${value} (UTC)`}>
      {formatDateTime(value)}
    </time>
  );
}

/** Día de referencia UTC (YYYY-MM-DD). */
export function Day({ value }: { value: string | null | undefined }) {
  if (!value) return <span className="faint">—</span>;
  return (
    <time dateTime={value} title={`${value} (día UTC)`}>
      {formatDay(value)}
    </time>
  );
}
