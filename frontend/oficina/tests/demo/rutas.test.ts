// @vitest-environment node
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { afterEach, describe, expect, it } from "vitest";

import { checkDemoDir, defaultDemoDir, defaultRealDbDir, isDemoDir, lastClosedUtcDay, MARKER } from "../../scripts/demo/rutas.mjs";

const ENV = {
  TEMP: "C:\\Users\\u\\AppData\\Local\\Temp",
  LOCALAPPDATA: "C:\\Users\\u\\AppData\\Local",
  OneDrive: "C:\\Users\\u\\OneDrive",
} as unknown as NodeJS.ProcessEnv;
const REPO = "C:\\Users\\u\\OneDrive\\HackRadar30";
const win = process.platform === "win32";

describe.runIf(win)("carpeta de la demostración (Windows)", () => {
  it("por defecto usa la carpeta temporal del sistema, fuera de OneDrive y de la base real", () => {
    const dir = defaultDemoDir(ENV);
    expect(dir).toBe("C:\\Users\\u\\AppData\\Local\\Temp\\hack30x-demo-simulada");
    expect(checkDemoDir(dir, { env: ENV, repoRoot: REPO, platform: "win32" })).toEqual([]);
  });

  it("rechaza rutas dentro de OneDrive o del repositorio", () => {
    const problems = checkDemoDir("C:\\Users\\u\\OneDrive\\HackRadar30\\tmp", { env: ENV, repoRoot: REPO, platform: "win32" });
    expect(problems).toContain("la ruta está dentro de OneDrive");
    expect(problems).toContain("la ruta está dentro del repositorio");
    expect(checkDemoDir("D:\\OneDrive - Empresa\\demo", { env: ENV, platform: "win32" })).toContain("la ruta está dentro de OneDrive");
  });

  it("rechaza la carpeta de la base REAL por defecto y sus ascendientes", () => {
    expect(defaultRealDbDir(ENV, "win32")).toBe("C:\\Users\\u\\AppData\\Local\\hack30x\\detectar");
    for (const dir of ["C:\\Users\\u\\AppData\\Local\\hack30x\\detectar", "C:\\Users\\u\\AppData\\Local\\hack30x"]) {
      expect(checkDemoDir(dir, { env: ENV, platform: "win32" })).toContain("la ruta coincide con la carpeta de la base real por defecto");
    }
  });

  it("rechaza rutas relativas", () => {
    expect(checkDemoDir("demo", { env: ENV, platform: "win32" })).toContain("la ruta debe ser absoluta");
  });
});

describe("marca de la carpeta", () => {
  let dir: string;
  afterEach(() => rmSync(dir, { recursive: true, force: true }));

  it("solo reconoce como propia una carpeta con la marca del procedimiento", () => {
    dir = mkdtempSync(join(tmpdir(), "e14-prueba-"));
    expect(isDemoDir(dir)).toBe(false);
    writeFileSync(join(dir, MARKER), JSON.stringify({ proposito: "otro" }));
    expect(isDemoDir(dir)).toBe(false);
    writeFileSync(join(dir, MARKER), "no es json");
    expect(isDemoDir(dir)).toBe(false);
    writeFileSync(join(dir, MARKER), JSON.stringify({ proposito: "demo-simulada-hack30x" }));
    expect(isDemoDir(dir)).toBe(true);
  });
});

describe("fecha de referencia", () => {
  it("es el último día cerrado en UTC, sin depender de la hora local", () => {
    expect(lastClosedUtcDay(new Date("2026-10-17T00:30:00Z"))).toBe("2026-10-16");
    expect(lastClosedUtcDay(new Date("2026-10-17T23:59:00Z"))).toBe("2026-10-16");
    expect(lastClosedUtcDay(new Date("2026-03-01T10:00:00Z"))).toBe("2026-02-28");
  });
});
