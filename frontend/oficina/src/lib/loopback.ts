/**
 * Comprobación de arranque: la oficina solo puede escuchar en loopback.
 *
 * - `next start` (argumentos visibles en el proceso): exige `--hostname`/`-H` de loopback.
 * - `next dev` (el servidor corre en un proceso hijo sin argumentos): exige la variable
 *   `OFICINA_HOSTNAME` que fija el lanzador `scripts/local.mjs` con el host que realmente usó.
 * - `next build` no arranca ningún servidor: no se comprueba.
 */
export const LOOPBACK_HOSTS = new Set(["127.0.0.1", "localhost", "::1", "[::1]"]);

function hostnameArg(argv: string[]): string | null | undefined {
  for (let i = 0; i < argv.length; i++) {
    const arg = argv[i]!;
    if (arg === "--hostname" || arg === "-H") return argv[i + 1] ?? null;
    if (arg.startsWith("--hostname=")) return arg.slice("--hostname=".length);
  }
  return undefined;
}

/** Devuelve el motivo para impedir el arranque, o null si es seguro. */
export function loopbackProblem(argv: string[], env: Record<string, string | undefined>): string | null {
  const args = argv.slice(1);
  if (args.includes("build") || env.NEXT_PHASE === "phase-production-build") return null;
  if (args.includes("start")) {
    const host = hostnameArg(args);
    if (!host) return "Falta --hostname 127.0.0.1: sin él, Next escucha en todas las interfaces de red.";
    if (!LOOPBACK_HOSTS.has(host.toLowerCase())) return `--hostname ${host} no es de loopback: la oficina no puede exponerse en red.`;
    return null;
  }
  const declared = env.OFICINA_HOSTNAME;
  if (!declared) return "Arranque de desarrollo sin el lanzador local: use `npm run dev` (fija 127.0.0.1).";
  if (!LOOPBACK_HOSTS.has(declared.toLowerCase())) return `OFICINA_HOSTNAME=${declared} no es de loopback.`;
  return null;
}
