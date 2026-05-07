"use client";

import { useEffect, useRef, useState } from "react";

type Phase =
  | "idle"
  | "uploading"
  | "queued"
  | "running"
  | "completed"
  | "failed";

type StatusResponse = {
  id: string;
  status: "IN_QUEUE" | "IN_PROGRESS" | "COMPLETED" | "FAILED" | "CANCELLED" | "TIMED_OUT";
  output?: { video_b64?: string; video_filename?: string; error?: string } | null;
  error?: string;
  delayTime?: number;
  executionTime?: number;
};

const DEFAULT_PROMPT =
  "A person speaking naturally to the camera, soft cinematic lighting, detailed, realistic.";

export default function Page() {
  const [imageFile, setImageFile] = useState<File | null>(null);
  const [audioFile, setAudioFile] = useState<File | null>(null);
  const [prompt, setPrompt] = useState(DEFAULT_PROMPT);
  const [negativePrompt, setNegativePrompt] = useState("");
  const [width, setWidth] = useState(832);
  const [height, setHeight] = useState(480);
  const [framesPerWindow, setFramesPerWindow] = useState(93);
  const [audioMaxSeconds, setAudioMaxSeconds] = useState<number | "">("");
  const [advanced, setAdvanced] = useState(false);

  const [phase, setPhase] = useState<Phase>("idle");
  const [jobId, setJobId] = useState<string | null>(null);
  const [statusInfo, setStatusInfo] = useState<StatusResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [videoUrl, setVideoUrl] = useState<string | null>(null);
  const [videoFilename, setVideoFilename] = useState<string>("longcat-avatar.mp4");
  const [elapsed, setElapsed] = useState(0);

  const startTimeRef = useRef<number | null>(null);
  const pollTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const elapsedTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const [config, setConfig] = useState<{ apiKeyConfigured: boolean; endpointConfigured: boolean } | null>(null);
  useEffect(() => {
    fetch("/api/health").then((r) => r.json()).then(setConfig).catch(() => setConfig(null));
  }, []);

  useEffect(() => {
    return () => {
      if (pollTimerRef.current) clearInterval(pollTimerRef.current);
      if (elapsedTimerRef.current) clearInterval(elapsedTimerRef.current);
      if (videoUrl) URL.revokeObjectURL(videoUrl);
    };
  }, [videoUrl]);

  const reset = () => {
    if (pollTimerRef.current) clearInterval(pollTimerRef.current);
    if (elapsedTimerRef.current) clearInterval(elapsedTimerRef.current);
    pollTimerRef.current = null;
    elapsedTimerRef.current = null;
    if (videoUrl) URL.revokeObjectURL(videoUrl);
    setVideoUrl(null);
    setStatusInfo(null);
    setError(null);
    setJobId(null);
    setElapsed(0);
    startTimeRef.current = null;
    setPhase("idle");
  };

  const submit = async () => {
    if (!imageFile || !audioFile) {
      setError("Görsel ve ses dosyası gerekli.");
      return;
    }
    reset();
    setPhase("uploading");

    try {
      const [imageB64, audioB64] = await Promise.all([
        readAsBase64(imageFile),
        readAsBase64(audioFile),
      ]);

      const res = await fetch("/api/generate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          image: imageB64,
          audio: audioB64,
          prompt,
          negative_prompt: negativePrompt || undefined,
          width,
          height,
          frames_per_window: framesPerWindow,
          audio_max_seconds: audioMaxSeconds || undefined,
        }),
      });

      const data = await res.json();
      if (!res.ok) throw new Error(data?.error ?? "İstek başarısız");

      setJobId(data.jobId);
      setPhase("queued");
      startTimeRef.current = Date.now();
      elapsedTimerRef.current = setInterval(() => {
        if (startTimeRef.current) {
          setElapsed(Math.floor((Date.now() - startTimeRef.current) / 1000));
        }
      }, 1000);

      pollTimerRef.current = setInterval(() => poll(data.jobId), 2500);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Bilinmeyen hata");
      setPhase("failed");
    }
  };

  const poll = async (id: string) => {
    try {
      const res = await fetch(`/api/status/${id}`);
      const data: StatusResponse = await res.json();
      setStatusInfo(data);

      if (data.status === "IN_PROGRESS") setPhase("running");
      else if (data.status === "IN_QUEUE") setPhase("queued");
      else if (data.status === "COMPLETED") {
        setPhase("completed");
        if (pollTimerRef.current) clearInterval(pollTimerRef.current);
        if (elapsedTimerRef.current) clearInterval(elapsedTimerRef.current);
        const out = data.output as any;
        if (out?.error) {
          setError(out.error);
          setPhase("failed");
          return;
        }
        if (out?.video_b64) {
          const blob = b64ToBlob(out.video_b64, "video/mp4");
          setVideoUrl(URL.createObjectURL(blob));
          setVideoFilename(out.video_filename ?? "longcat-avatar.mp4");
        }
      } else if (
        data.status === "FAILED" ||
        data.status === "CANCELLED" ||
        data.status === "TIMED_OUT"
      ) {
        setPhase("failed");
        setError(data.error ?? `Job ${data.status}`);
        if (pollTimerRef.current) clearInterval(pollTimerRef.current);
        if (elapsedTimerRef.current) clearInterval(elapsedTimerRef.current);
      }
    } catch (err) {
      // transient — keep polling
    }
  };

  const busy = phase === "uploading" || phase === "queued" || phase === "running";

  return (
    <main className="mx-auto max-w-3xl p-6 lg:p-10">
      <header className="mb-8 flex items-baseline justify-between">
        <div>
          <h1 className="text-3xl font-semibold tracking-tight">LongCat Avatar</h1>
          <p className="text-sm text-neutral-400">
            Görsel + ses → konuşan avatar videosu, RunPod Serverless üzerinden.
          </p>
        </div>
        <ConfigBadge config={config} />
      </header>

      <section className="space-y-5 rounded-2xl border border-neutral-800 bg-neutral-900/50 p-6">
        <div className="grid gap-4 sm:grid-cols-2">
          <FileField
            label="Referans portre"
            accept="image/png,image/jpeg,image/webp"
            file={imageFile}
            onChange={setImageFile}
            preview="image"
          />
          <FileField
            label="Konuşma sesi"
            accept="audio/wav,audio/mpeg,audio/mp3,audio/x-wav"
            file={audioFile}
            onChange={setAudioFile}
            preview="audio"
          />
        </div>

        <div>
          <label className="mb-1 block text-sm text-neutral-300">Sahne tarifi (prompt)</label>
          <textarea
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            rows={3}
            className="w-full rounded-lg border border-neutral-700 bg-neutral-950 p-3 text-sm focus:border-neutral-500 focus:outline-none"
          />
        </div>

        <button
          type="button"
          onClick={() => setAdvanced((v) => !v)}
          className="text-xs text-neutral-400 hover:text-neutral-200"
        >
          {advanced ? "− Gelişmiş ayarları gizle" : "+ Gelişmiş ayarlar"}
        </button>

        {advanced && (
          <div className="grid gap-4 rounded-lg border border-neutral-800 bg-neutral-950/60 p-4 sm:grid-cols-2">
            <NumberField label="Genişlik (px)" value={width} onChange={setWidth} step={32} />
            <NumberField label="Yükseklik (px)" value={height} onChange={setHeight} step={32} />
            <NumberField
              label="Pencere başına frame"
              value={framesPerWindow}
              onChange={setFramesPerWindow}
              step={20}
              hint="93 ≈ 5.8s @ 16fps"
            />
            <NumberField
              label="Ses kırpma (saniye)"
              value={audioMaxSeconds === "" ? 0 : audioMaxSeconds}
              onChange={(v) => setAudioMaxSeconds(v || "")}
              step={1}
              hint="0 = kırpma yok"
            />
            <div className="sm:col-span-2">
              <label className="mb-1 block text-sm text-neutral-300">Negative prompt</label>
              <textarea
                value={negativePrompt}
                onChange={(e) => setNegativePrompt(e.target.value)}
                rows={2}
                placeholder="Boş bırakılırsa workflow'un varsayılanı kullanılır."
                className="w-full rounded-lg border border-neutral-700 bg-neutral-950 p-3 text-sm focus:border-neutral-500 focus:outline-none"
              />
            </div>
          </div>
        )}

        <div className="flex items-center justify-between gap-3 pt-2">
          <button
            type="button"
            disabled={busy || !config?.apiKeyConfigured || !config?.endpointConfigured}
            onClick={submit}
            className="rounded-lg bg-emerald-500 px-5 py-2.5 text-sm font-medium text-neutral-950 transition hover:bg-emerald-400 disabled:cursor-not-allowed disabled:bg-neutral-700 disabled:text-neutral-400"
          >
            {busy ? "Çalışıyor…" : "Çalıştır"}
          </button>
          {phase !== "idle" && (
            <button
              type="button"
              onClick={reset}
              disabled={busy}
              className="text-xs text-neutral-400 hover:text-neutral-200 disabled:opacity-50"
            >
              Sıfırla
            </button>
          )}
        </div>
      </section>

      {(phase !== "idle" || error) && (
        <section className="mt-6 rounded-2xl border border-neutral-800 bg-neutral-900/50 p-6">
          <StatusPanel
            phase={phase}
            elapsed={elapsed}
            jobId={jobId}
            statusInfo={statusInfo}
            error={error}
          />
          {videoUrl && (
            <div className="mt-5 space-y-3">
              <video src={videoUrl} controls className="w-full rounded-lg" />
              <a
                href={videoUrl}
                download={videoFilename}
                className="inline-block rounded-lg border border-neutral-700 px-3 py-1.5 text-xs hover:border-neutral-500"
              >
                ⬇ İndir ({videoFilename})
              </a>
            </div>
          )}
        </section>
      )}
    </main>
  );
}

function ConfigBadge({ config }: { config: { apiKeyConfigured: boolean; endpointConfigured: boolean } | null }) {
  if (!config) return null;
  const ok = config.apiKeyConfigured && config.endpointConfigured;
  return (
    <span
      className={
        "rounded-full px-2.5 py-1 text-xs " +
        (ok
          ? "border border-emerald-700/60 bg-emerald-900/30 text-emerald-300"
          : "border border-amber-700/60 bg-amber-900/30 text-amber-300")
      }
      title={ok ? "RunPod yapılandırıldı" : ".env.local içinde RUNPOD_API_KEY ve RUNPOD_ENDPOINT_ID eksik"}
    >
      {ok ? "● bağlı" : "● eksik config"}
    </span>
  );
}

function FileField({
  label,
  accept,
  file,
  onChange,
  preview,
}: {
  label: string;
  accept: string;
  file: File | null;
  onChange: (f: File | null) => void;
  preview: "image" | "audio";
}) {
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  useEffect(() => {
    if (!file) {
      setPreviewUrl(null);
      return;
    }
    const url = URL.createObjectURL(file);
    setPreviewUrl(url);
    return () => URL.revokeObjectURL(url);
  }, [file]);

  return (
    <div>
      <label className="mb-1 block text-sm text-neutral-300">{label}</label>
      <label className="flex cursor-pointer items-center justify-center rounded-lg border border-dashed border-neutral-700 bg-neutral-950 p-4 text-sm text-neutral-400 hover:border-neutral-500">
        <input
          type="file"
          accept={accept}
          className="hidden"
          onChange={(e) => onChange(e.target.files?.[0] ?? null)}
        />
        {file ? (
          <span className="truncate">{file.name}</span>
        ) : (
          <span>Tıkla veya sürükle bırak</span>
        )}
      </label>
      {previewUrl && preview === "image" && (
        <img src={previewUrl} alt="" className="mt-2 max-h-40 rounded-lg border border-neutral-800" />
      )}
      {previewUrl && preview === "audio" && (
        <audio src={previewUrl} controls className="mt-2 w-full" />
      )}
    </div>
  );
}

function NumberField({
  label,
  value,
  onChange,
  step,
  hint,
}: {
  label: string;
  value: number;
  onChange: (v: number) => void;
  step?: number;
  hint?: string;
}) {
  return (
    <div>
      <label className="mb-1 block text-sm text-neutral-300">{label}</label>
      <input
        type="number"
        value={value}
        step={step ?? 1}
        onChange={(e) => onChange(Number(e.target.value))}
        className="w-full rounded-lg border border-neutral-700 bg-neutral-950 p-2 text-sm focus:border-neutral-500 focus:outline-none"
      />
      {hint && <p className="mt-1 text-xs text-neutral-500">{hint}</p>}
    </div>
  );
}

function StatusPanel({
  phase,
  elapsed,
  jobId,
  statusInfo,
  error,
}: {
  phase: Phase;
  elapsed: number;
  jobId: string | null;
  statusInfo: StatusResponse | null;
  error: string | null;
}) {
  const phaseText: Record<Phase, string> = {
    idle: "Hazır.",
    uploading: "Dosyalar yükleniyor…",
    queued: "Sıraya alındı (worker soğuk başlatma olabilir, ~60s)",
    running: "Çalışıyor (avatar üretiliyor)",
    completed: "Tamamlandı.",
    failed: "Başarısız.",
  };
  return (
    <div>
      <div className="flex items-center justify-between">
        <span className="text-sm text-neutral-300">{phaseText[phase]}</span>
        {phase !== "idle" && phase !== "completed" && phase !== "failed" && (
          <span className="text-xs tabular-nums text-neutral-500">
            geçen süre: {elapsed}s
          </span>
        )}
      </div>
      {(jobId || statusInfo) && (
        <dl className="mt-3 grid grid-cols-[max-content_1fr] gap-x-4 gap-y-1 text-xs text-neutral-500">
          {jobId && (
            <>
              <dt>job</dt>
              <dd className="break-all font-mono text-neutral-400">{jobId}</dd>
            </>
          )}
          {statusInfo?.delayTime !== undefined && (
            <>
              <dt>delay</dt>
              <dd className="tabular-nums text-neutral-400">{Math.round(statusInfo.delayTime / 100) / 10}s</dd>
            </>
          )}
          {statusInfo?.executionTime !== undefined && (
            <>
              <dt>exec</dt>
              <dd className="tabular-nums text-neutral-400">{Math.round(statusInfo.executionTime / 100) / 10}s</dd>
            </>
          )}
        </dl>
      )}
      {error && (
        <p className="mt-3 rounded-lg border border-red-900/60 bg-red-950/40 p-3 text-xs text-red-300">
          {error}
        </p>
      )}
    </div>
  );
}

function readAsBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve((reader.result as string) ?? "");
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(file);
  });
}

function b64ToBlob(b64: string, mime: string): Blob {
  const clean = b64.includes("base64,") ? b64.split("base64,")[1] : b64;
  const bin = atob(clean);
  const buf = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) buf[i] = bin.charCodeAt(i);
  return new Blob([buf], { type: mime });
}
