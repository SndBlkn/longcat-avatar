import { NextResponse } from "next/server";

export const runtime = "nodejs";

export async function GET() {
  const apiKey = process.env.RUNPOD_API_KEY;
  const endpointId = process.env.RUNPOD_ENDPOINT_ID;
  return NextResponse.json({
    apiKeyConfigured: Boolean(apiKey),
    endpointConfigured: Boolean(endpointId),
  });
}
