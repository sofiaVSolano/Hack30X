import { handleRead } from "@/server/handler";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export async function GET(request: Request, context: { params: Promise<{ tema: string }> }): Promise<Response> {
  return handleRead("tema", request, await context.params);
}
