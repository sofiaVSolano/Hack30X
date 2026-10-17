import { handleRead } from "@/server/handler";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export async function GET(request: Request, context: { params: Promise<{ agente: string }> }): Promise<Response> {
  return handleRead("agenteEjecuciones", request, await context.params);
}
