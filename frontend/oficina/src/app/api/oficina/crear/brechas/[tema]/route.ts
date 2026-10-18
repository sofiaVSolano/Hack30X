import { handleCrear } from "@/server/crear/handler";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export async function GET(request: Request, context: { params: Promise<{ tema: string }> }): Promise<Response> {
  return handleCrear("brecha", request, await context.params);
}
