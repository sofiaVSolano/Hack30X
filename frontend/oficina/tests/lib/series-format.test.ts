import { describe, expect, it } from "vitest";

import { durationMs, formatDuration, formatMetricValue } from "@/lib/format";
import { buildSeries } from "@/lib/series";

import { metric } from "../support/fixtures";

describe("buildSeries", () => {
  it("sin valores -> empty", () => {
    expect(buildSeries([])).toEqual({ kind: "empty" });
  });

  it("corta la línea en días no consecutivos y no inventa ceros", () => {
    const result = buildSeries([
      metric({ fecha_referencia: "2026-10-10", valor: 10 }),
      metric({ fecha_referencia: "2026-10-11", valor: 12 }),
      metric({ fecha_referencia: "2026-10-14", valor: 30 }),
      metric({ fecha_referencia: "2026-10-15", valor: 31 }),
    ]);
    expect(result.kind).toBe("ok");
    if (result.kind !== "ok") return;
    const [series] = result.series;
    expect(series!.points.map((p) => p.value)).toEqual([10, 12, 30, 31]);
    expect(series!.segments.map((s) => s.map((p) => p.date))).toEqual([
      ["2026-10-10", "2026-10-11"],
      ["2026-10-14", "2026-10-15"],
    ]);
    expect(series!.points.some((p) => p.value === 0)).toBe(false);
  });

  it("los valores insuficientes son huecos marcados, no puntos", () => {
    const result = buildSeries([
      metric({ fecha_referencia: "2026-10-10", valor: 10 }),
      metric({ fecha_referencia: "2026-10-11", valor: null, estado: "insufficient", motivo: "sin datos" }),
      metric({ fecha_referencia: "2026-10-12", valor: 14 }),
      metric({ fecha_referencia: "2026-10-13", valor: 15 }),
    ]);
    if (result.kind !== "ok") throw new Error(result.kind);
    const [series] = result.series;
    expect(series!.insufficient).toEqual(["2026-10-11"]);
    expect(series!.segments).toHaveLength(2);
  });

  it("cada ámbito es una serie distinta; nunca se suman", () => {
    const result = buildSeries([
      metric({ ambito: "MX", fecha_referencia: "2026-10-10", valor: 1 }),
      metric({ ambito: "MX", fecha_referencia: "2026-10-11", valor: 2 }),
      metric({ ambito: "CO", fecha_referencia: "2026-10-10", valor: 5 }),
    ]);
    if (result.kind !== "ok") throw new Error(result.kind);
    expect(result.series.map((s) => [s.scope, s.points.length])).toEqual([
      ["CO", 1],
      ["MX", 2],
    ]);
  });

  it.each([
    [{ fuente: "gdelt" as const, unidad: "articles" }, "fuente"],
    [{ metrica: "wiki_views_growth", unidad: "growth_rate" }, "métrica"],
    [{ ventana_dias: 14 }, "ventana"],
    [{ data_mode: "simulated" as const }, "modo de datos"],
  ])("se niega a mezclar %o", (other, word) => {
    const result = buildSeries([metric(), metric({ fecha_referencia: "2026-10-14", ...other })]);
    expect(result.kind).toBe("mixed");
    if (result.kind === "mixed") expect(result.reason).toContain(word);
  });

  it("con menos de dos puntos válidos por ámbito no hay serie", () => {
    const result = buildSeries([metric(), metric({ fecha_referencia: "2026-10-14", valor: null, estado: "insufficient" })]);
    expect(result.kind).toBe("insufficient");
  });
});

describe("formato", () => {
  it("un valor nulo es «sin valor», no cero", () => {
    expect(formatMetricValue(null, "views")).toBe("sin valor");
  });

  it("la cota inferior de búsquedas conserva su significado", () => {
    expect(formatMetricValue(20000, "searches_lower_bound")).toMatch(/^≥ 20.000$/);
  });

  it("las tasas son fracciones con signo, sin convertir a porcentaje", () => {
    expect(formatMetricValue(0.35, "growth_rate")).toBe("+0,350");
    expect(formatMetricValue(0.35, "growth_rate")).not.toContain("%");
  });

  it("la duración requiere inicio y fin", () => {
    expect(durationMs("2026-10-16T21:00:00Z", null)).toBeNull();
    expect(durationMs(null, "2026-10-16T21:00:00Z")).toBeNull();
    expect(durationMs("2026-10-16T21:00:10Z", "2026-10-16T21:00:00Z")).toBeNull();
    expect(formatDuration(durationMs("2026-10-16T21:00:00Z", "2026-10-16T21:01:30Z"))).toBe("1 min 30 s");
    expect(formatDuration(null)).toBe("—");
    // marcas con precisión de segundos: menos de un segundo no se muestra como «0 ms»
    expect(formatDuration(durationMs("2026-10-16T21:00:00Z", "2026-10-16T21:00:00Z"))).toBe("< 1 s");
  });
});
