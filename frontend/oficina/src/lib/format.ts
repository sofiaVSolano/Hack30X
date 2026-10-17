import { UNIT } from "./labels";

const dateTime = new Intl.DateTimeFormat("es", { dateStyle: "medium", timeStyle: "short" });
const dateOnly = new Intl.DateTimeFormat("es", { dateStyle: "medium", timeZone: "UTC" });

export function parseDate(value: string | null | undefined): Date | null {
  if (!value) return null;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}

/** Fecha y hora local; el valor UTC original va en el atributo `dateTime` de <time>. */
export function formatDateTime(value: string | null | undefined): string {
  const date = parseDate(value);
  return date ? dateTime.format(date) : "—";
}

/** Fechas de referencia (YYYY-MM-DD): son días UTC, se muestran sin desplazar la zona. */
export function formatDay(value: string | null | undefined): string {
  if (!value || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return value ?? "—";
  return dateOnly.format(new Date(`${value}T00:00:00Z`));
}

export function formatRelative(date: Date | undefined, now: Date = new Date()): string {
  if (!date) return "sin datos";
  const seconds = Math.round((now.getTime() - date.getTime()) / 1000);
  if (seconds < 5) return "ahora mismo";
  if (seconds < 60) return `hace ${seconds} s`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `hace ${minutes} min`;
  const hours = Math.floor(minutes / 60);
  return `hace ${hours} h`;
}

/** Duración solo si existen ambos extremos y el orden es coherente; si no, null. */
export function durationMs(start: string | null, end: string | null): number | null {
  const a = parseDate(start);
  const b = parseDate(end);
  if (!a || !b) return null;
  const ms = b.getTime() - a.getTime();
  return ms >= 0 ? ms : null;
}

export function formatDuration(ms: number | null): string {
  if (ms === null) return "—";
  // La API devuelve marcas de tiempo con precisión de segundos: no se aparenta más precisión.
  if (ms < 1000) return "< 1 s";
  const totalSeconds = Math.round(ms / 1000);
  if (totalSeconds < 60) return `${totalSeconds} s`;
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  if (minutes < 60) return seconds ? `${minutes} min ${seconds} s` : `${minutes} min`;
  const hours = Math.floor(minutes / 60);
  return `${hours} h ${minutes % 60} min`;
}

export function formatMinutes(minutes: number | null): string {
  if (minutes === null) return "—";
  if (minutes < 60) return `cada ${minutes} min`;
  if (minutes % 1440 === 0) return `cada ${minutes / 1440} d`;
  if (minutes % 60 === 0) return `cada ${minutes / 60} h`;
  return `cada ${Math.floor(minutes / 60)} h ${minutes % 60} min`;
}

/** Valor de una métrica en su unidad original. `null` significa «sin valor», nunca cero. */
export function formatMetricValue(value: number | null, unit: string): string {
  if (value === null) return "sin valor";
  const spec = UNIT[unit];
  const decimals = spec?.decimals ?? 3;
  const formatted = new Intl.NumberFormat("es", {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
    signDisplay: spec?.signed ? "exceptZero" : "auto",
  }).format(value);
  return `${spec?.prefix ?? ""}${formatted}`;
}

export function unitLabel(unit: string): string {
  return UNIT[unit]?.text ?? unit;
}
