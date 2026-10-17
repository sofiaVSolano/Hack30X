// @vitest-environment node
import { existsSync, readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative, sep } from "node:path";

import { describe, expect, it } from "vitest";

const ROOT = join(__dirname, "..", "..");
const SRC = join(ROOT, "src");

function walk(dir: string, out: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    const full = join(dir, name);
    if (statSync(full).isDirectory()) walk(full, out);
    else out.push(full);
  }
  return out;
}

const sources = walk(SRC).filter((f) => /\.(ts|tsx)$/.test(f));
const isServer = (f: string) => f.includes(`${sep}server${sep}`) || f.includes(`${sep}api${sep}oficina${sep}`);

describe("el token no llega al código del cliente", () => {
  it("solo src/server lee variables de entorno", () => {
    // proxy.ts e instrumentation.ts también se ejecutan solo en el servidor (PORT, NEXT_RUNTIME),
    // pero tampoco pueden leer el token: solo src/server/config.ts lo hace.
    const serverOnlyRuntime = new Set([join(SRC, "proxy.ts"), join(SRC, "instrumentation.ts"), join(SRC, "instrumentation-node.ts")]);
    for (const file of sources) {
      const text = readFileSync(file, "utf8");
      if (file.includes(`${sep}server${sep}`)) continue;
      if (serverOnlyRuntime.has(file)) {
        expect(text, relative(ROOT, file)).not.toMatch(/DETECTAR_ADMIN_TOKEN/);
        continue;
      }
      expect(text, relative(ROOT, file)).not.toMatch(/process\.env|DETECTAR_ADMIN_TOKEN/);
    }
  });

  it("ninguna variable usa el prefijo NEXT_PUBLIC_", () => {
    for (const file of [...sources, join(ROOT, ".env.example"), join(ROOT, "next.config.ts")]) {
      // Se prohíbe definir o leer variables públicas; mencionarlas en un comentario de aviso es válido.
      expect(readFileSync(file, "utf8"), relative(ROOT, file)).not.toMatch(/^\s*NEXT_PUBLIC_\w*=|env\.NEXT_PUBLIC_|env\[["']NEXT_PUBLIC_/m);
    }
  });

  it("los módulos del servidor importan server-only", () => {
    for (const file of sources.filter((f) => f.includes(`${sep}server${sep}`))) {
      expect(readFileSync(file, "utf8"), relative(ROOT, file)).toMatch(/^import "server-only";/m);
    }
  });

  it("ningún componente del cliente importa módulos del servidor", () => {
    for (const file of sources.filter((f) => !isServer(f))) {
      expect(readFileSync(file, "utf8"), relative(ROOT, file)).not.toMatch(/from "@\/server\//);
    }
  });

  it("el cliente solo llama al intermediario del mismo origen", () => {
    for (const file of sources.filter((f) => !isServer(f))) {
      const text = readFileSync(file, "utf8");
      expect(text, relative(ROOT, file)).not.toMatch(/\/api\/detectar|127\.0\.0\.1:8000|Authorization/);
    }
  });

  it("el ejemplo de entorno no contiene un token", () => {
    const example = readFileSync(join(ROOT, ".env.example"), "utf8");
    expect(example).toMatch(/^DETECTAR_ADMIN_TOKEN=$/m);
  });

  it.skipIf(!existsSync(join(ROOT, ".next", "static")))("el bundle público compilado no menciona la variable del token", () => {
    for (const file of walk(join(ROOT, ".next", "static"))) {
      if (!/\.(js|css|html|json)$/.test(file)) continue;
      expect(readFileSync(file, "utf8"), relative(ROOT, file)).not.toContain("DETECTAR_ADMIN_TOKEN");
    }
  });
});

describe("honestidad de los datos en el código", () => {
  it("no hay campos de saturación, oportunidad ni confianza en los esquemas", () => {
    const schemas = readFileSync(join(SRC, "lib", "schemas.ts"), "utf8").replace(/\/\*[\s\S]*?\*\//g, "");
    expect(schemas).not.toMatch(/saturacion|oportunidad|confianza/);
  });

  it("la aplicación no importa los datos de prueba", () => {
    for (const file of sources) {
      expect(readFileSync(file, "utf8"), relative(ROOT, file)).not.toMatch(/tests\/support|fixtures/);
    }
  });
});
