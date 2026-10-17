// Compila la oficina con un token CANARIO y comprueba que no aparece en ningún archivo que
// pueda llegar al navegador (.next/static y las páginas HTML prerenderizadas).
// Uso: npm run verificar:bundle
import { execSync } from "node:child_process";
import { randomBytes } from "node:crypto";
import { existsSync, readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";

const root = new URL("..", import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1");
const canary = `canario_${randomBytes(12).toString("hex")}`;

execSync("npx next build", {
  cwd: root,
  stdio: "inherit",
  env: { ...process.env, NEXT_TELEMETRY_DISABLED: "1", DETECTAR_ADMIN_TOKEN: canary, OFICINA_DETECTAR_URL: "http://127.0.0.1:9" },
});

function walk(dir, out = []) {
  if (!existsSync(dir)) return out;
  for (const name of readdirSync(dir)) {
    const full = join(dir, name);
    if (statSync(full).isDirectory()) walk(full, out);
    else out.push(full);
  }
  return out;
}

const publicFiles = [
  ...walk(join(root, ".next", "static")),
  ...walk(join(root, ".next", "server", "app")).filter((f) => /\.(html|rsc|body|meta)$/.test(f)),
];
const leaks = [];
for (const file of publicFiles) {
  const text = readFileSync(file, "utf8");
  if (text.includes(canary)) leaks.push(`${relative(root, file)}: contiene el token canario`);
  if (text.includes("DETECTAR_ADMIN_TOKEN")) leaks.push(`${relative(root, file)}: menciona DETECTAR_ADMIN_TOKEN`);
}
console.log(`Archivos públicos revisados: ${publicFiles.length}`);
if (leaks.length) {
  console.error(leaks.join("\n"));
  process.exit(1);
}
console.log("OK: el token no aparece en el código ni en las páginas que recibe el navegador.");
