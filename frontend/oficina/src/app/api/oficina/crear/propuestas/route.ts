import { handleCrear } from "@/server/crear/handler";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export async function GET(request: Request): Promise<Response> {
  return handleCrear("propuestas", request);
}

export async function POST(request: Request): Promise<Response> {
  return handleCrear("generar", request);
}
