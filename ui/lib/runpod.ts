const API_BASE = process.env.RUNPOD_API_BASE ?? "https://api.runpod.ai/v2";

function requireEnv(): { apiKey: string; endpointId: string } {
  const apiKey = process.env.RUNPOD_API_KEY;
  const endpointId = process.env.RUNPOD_ENDPOINT_ID;
  if (!apiKey || !endpointId) {
    throw new Error(
      "RUNPOD_API_KEY ve RUNPOD_ENDPOINT_ID .env.local dosyasında tanımlı olmalı.",
    );
  }
  return { apiKey, endpointId };
}

export async function submitJob(input: Record<string, unknown>): Promise<{ id: string; status: string }> {
  const { apiKey, endpointId } = requireEnv();
  const res = await fetch(`${API_BASE}/${endpointId}/run`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${apiKey}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ input }),
  });
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`RunPod /run failed (${res.status}): ${body}`);
  }
  return res.json();
}

export interface JobStatus {
  id: string;
  status: "IN_QUEUE" | "IN_PROGRESS" | "COMPLETED" | "FAILED" | "CANCELLED" | "TIMED_OUT";
  output?: unknown;
  error?: string;
  delayTime?: number;
  executionTime?: number;
}

export async function getStatus(jobId: string): Promise<JobStatus> {
  const { apiKey, endpointId } = requireEnv();
  const res = await fetch(`${API_BASE}/${endpointId}/status/${jobId}`, {
    method: "GET",
    headers: { Authorization: `Bearer ${apiKey}` },
    cache: "no-store",
  });
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`RunPod /status failed (${res.status}): ${body}`);
  }
  return res.json();
}

export async function cancelJob(jobId: string): Promise<void> {
  const { apiKey, endpointId } = requireEnv();
  await fetch(`${API_BASE}/${endpointId}/cancel/${jobId}`, {
    method: "POST",
    headers: { Authorization: `Bearer ${apiKey}` },
  });
}
