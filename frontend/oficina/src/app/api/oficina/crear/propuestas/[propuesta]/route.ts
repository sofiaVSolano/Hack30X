import { handleCrear } from "@/server/crear/handler";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export async function GET(request: Request, context: { params: Promise<{ propuesta: string }> }): Promise<Response> {
  return handleCrear("propuesta", request, await context.params);
}
