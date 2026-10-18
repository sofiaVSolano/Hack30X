import { handleCrear } from "@/server/crear/handler";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export async function GET(request: Request): Promise<Response> {
  return handleCrear("reglas", request);
}
