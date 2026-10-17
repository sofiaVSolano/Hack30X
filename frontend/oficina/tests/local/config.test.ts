// @vitest-environment node
import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import { checkConfigPath, parseConfig, projectEnvWithToken } from "../../scripts/local/config.mjs";

const ENV = { OneDrive: "C:\\Users\\u\\OneDrive" } as unknown as NodeJS.ProcessEnv;
const win = process.platform === "win32";

describe.runIf(win)("ubicación del archivo de secretos", () => {
  it("acepta %LOCALAPPDATA%, fuera de OneDrive y del repositorio", () => {
    expect(
      checkConfigPath("C:\\Users\\u\\AppData\\Local\\hack30x\\oficina\\oficina.env", { env: ENV, repoRoot: "C:\\Users\\u\\OneDrive\\HackRadar30" }),
    ).toEqual([]);
  });

  it("rechaza OneDrive, el repositorio y rutas relativas", () => {
    const repo = "C:\\Users\\u\\OneDrive\\HackRadar30";
    expect(checkConfigPath(`${repo}\\frontend\\oficina\\.env.local`, { env: ENV, repoRoot: repo })).toEqual([
      "está dentro de OneDrive",
      "está dentro del repositorio",
    ]);
    expect(checkConfigPath("D:\\OneDrive - Empresa\\oficina.env", { env: ENV })).toContain("está dentro de OneDrive");
    expect(checkConfigPath("oficina.env", { env: ENV })).toContain("la ruta debe ser absoluta");
  });
});

describe("lectura de la configuración", () => {
  it("lee las claves admitidas y quita comillas", () => {
    const { values, errors } = parseConfig('# comentario\nOFICINA_DETECTAR_URL=http://127.0.0.1:8000\nDETECTAR_ADMIN_TOKEN="abc def"\n\n');
    expect(errors).toEqual([]);
    expect(values).toEqual({ OFICINA_DETECTAR_URL: "http://127.0.0.1:8000", DETECTAR_ADMIN_TOKEN: "abc def" });
  });

  it("rechaza claves desconocidas, repetidas o líneas mal formadas sin revelar valores", () => {
    const secret = "valor-secreto-que-no-debe-aparecer";
    const { errors } = parseConfig(`NEXT_PUBLIC_TOKEN=${secret}\nDETECTAR_ADMIN_TOKEN=${secret}\nDETECTAR_ADMIN_TOKEN=${secret}\nsolo-texto-${secret}`);
    expect(errors).toHaveLength(3);
    expect(errors.join(" ")).not.toContain(secret);
    expect(errors[0]).toMatch(/clave no admitida \(NEXT_PUBLIC_TOKEN\)/);
  });
});

describe("archivos .env del proyecto con el token", () => {
  const files: Record<string, string> = {
    ".env.example": "DETECTAR_ADMIN_TOKEN=\n",
    ".env.local": "OFICINA_DETECTAR_URL=http://127.0.0.1:8000\nDETECTAR_ADMIN_TOKEN=algo\n",
    ".env": "# DETECTAR_ADMIN_TOKEN=comentado\n",
    "package.json": "DETECTAR_ADMIN_TOKEN=x",
  };
  const read = (file: string) => files[file.split(/[\\/]/).pop()!]!;

  it("detecta solo los .env reales con un token definido (no el ejemplo, comentarios ni otros archivos)", () => {
    expect(projectEnvWithToken("dir", Object.keys(files), read)).toEqual([".env.local"]);
  });

  it("el ejemplo versionado no contiene un token", () => {
    expect(readFileSync(join(__dirname, "..", "..", ".env.example"), "utf8")).toMatch(/^DETECTAR_ADMIN_TOKEN=$/m);
  });
});
