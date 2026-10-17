import { loopbackProblem } from "./lib/loopback";

export function enforceLoopback(): void {
  const problem = loopbackProblem(process.argv, process.env);
  if (problem) {
    console.error(`[oficina] Arranque bloqueado. ${problem}`);
    process.exit(1);
  }
}
