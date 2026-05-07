import { NextRequest, NextResponse } from "next/server";
import { getStatus } from "@/lib/runpod";

export const runtime = "nodejs";

export async function GET(_req: NextRequest, { params }: { params: { id: string } }) {
  try {
    const status = await getStatus(params.id);
    return NextResponse.json(status);
  } catch (err) {
    return NextResponse.json(
      { error: err instanceof Error ? err.message : "Bilinmeyen hata" },
      { status: 500 },
    );
  }
}
