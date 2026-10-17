// Se ejecuta al arrancar el servidor de Next: impide servir la oficina fuera de loopback.
// La comprobación usa APIs de Node, así que vive en un módulo que solo se carga en ese runtime.
export async function register(): Promise<void> {
  if (process.env.NEXT_RUNTIME === "nodejs") {
    const { enforceLoopback } = await import("./instrumentation-node");
    enforceLoopback();
  }
}
