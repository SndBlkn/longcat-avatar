import { NextRequest, NextResponse } from "next/server";
import { submitJob } from "@/lib/runpod";

export const runtime = "nodejs";
export const maxDuration = 60;

export async function POST(req: NextRequest) {
  try {
    const body = await req.json();

    const required = ["image", "audio", "prompt"] as const;
    for (const key of required) {
      if (!body?.[key] || typeof body[key] !== "string") {
        return NextResponse.json(
          { error: `Eksik / hatalı alan: ${key}` },
          { status: 400 },
        );
      }
    }

    const input: Record<string, unknown> = {
      image: stripDataUrl(body.image),
      audio: stripDataUrl(body.audio),
      prompt: body.prompt,
    };
    if (body.negative_prompt) input.negative_prompt = body.negative_prompt;
    if (body.width) input.width = Number(body.width);
    if (body.height) input.height = Number(body.height);
    if (body.frames_per_window) input.frames_per_window = Number(body.frames_per_window);
    if (body.overlap !== undefined) input.overlap = Number(body.overlap);
    if (body.cfg !== undefined) input.cfg = Number(body.cfg);
    if (body.audio_max_seconds) input.audio_max_seconds = Number(body.audio_max_seconds);

    const job = await submitJob(input);
    return NextResponse.json({ jobId: job.id, status: job.status });
  } catch (err) {
    return NextResponse.json(
      { error: err instanceof Error ? err.message : "Bilinmeyen hata" },
      { status: 500 },
    );
  }
}

function stripDataUrl(value: string): string {
  const idx = value.indexOf("base64,");
  return idx >= 0 ? value.slice(idx + "base64,".length) : value;
}
