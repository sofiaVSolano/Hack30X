import { handleCrear } from "@/server/crear/handler";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export async function POST(request: Request, context: { params: Promise<{ propuesta: string }> }): Promise<Response> {
  return handleCrear("regenerar", request, await context.params);
}
