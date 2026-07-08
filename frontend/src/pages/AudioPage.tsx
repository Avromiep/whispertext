/** Audio settings: device picker, live level meter, processing toggles, mic test. */
import { useEffect, useRef, useState } from "react";
import { Mic } from "lucide-react";
import { api, AudioDevice } from "../lib/api";
import { useBackendEvents } from "../lib/ws";
import { useSettings } from "../hooks/useSettings";
import { Button, PageHeader, Section, Select, Toggle } from "../components/ui";

export default function AudioPage() {
  const { settings, patch } = useSettings();
  const [devices, setDevices] = useState<AudioDevice[]>([]);
  const [testing, setTesting] = useState(false);
  const [testText, setTestText] = useState("");
  const level = useRef(0);
  const meterRef = useRef<HTMLDivElement>(null);

  useEffect(() => { api.audioDevices().then(setDevices).catch(() => {}); }, []);

  useBackendEvents((e) => {
    if (e.type === "audio_level" && typeof e.level === "number") level.current = e.level;
  });

  // Smooth meter without re-rendering React on every audio block.
  useEffect(() => {
    let raf = 0;
    let displayed = 0;
    const tick = () => {
      displayed += (level.current - displayed) * 0.25;
      level.current *= 0.97; // decay when no events arrive
      if (meterRef.current) meterRef.current.style.width = `${Math.min(100, displayed * 100)}%`;
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, []);

  if (!settings) return null;
  const a = settings.audio;

  const runMicTest = async () => {
    setTesting(true);
    setTestText("");
    try {
      const r = await api.dictationTest(3);
      setTestText(r.text || "(no speech detected)");
    } catch (e) {
      setTestText(`Microphone test failed: ${e}`);
    } finally {
      setTesting(false);
    }
  };

  return (
    <div className="animate-fade-in">
      <PageHeader title="Audio" subtitle="Microphone and recording quality." />

      <Section title="Microphone">
        <Select
          label="Input device"
          value={String(a.input_device ?? "default")}
          onChange={(v) => patch({ audio: { input_device: v === "default" ? null : Number(v) } })}
          options={[
            { value: "default", label: "System default" },
            ...devices.map((d) => ({ value: String(d.id), label: `${d.name}${d.default ? " (default)" : ""}` })),
          ]}
        />
        <div className="mt-4">
          <div className="text-xs text-muted mb-1.5">Input level (live while recording)</div>
          <div className="h-2 rounded-full bg-elevated overflow-hidden">
            <div ref={meterRef} className="h-full bg-gradient-to-r from-emerald-500 to-accent transition-none" style={{ width: 0 }} />
          </div>
        </div>
        <div className="mt-4 flex items-center gap-3">
          <Button size="sm" onClick={runMicTest} disabled={testing}>
            <Mic size={13} /> {testing ? "Listening… speak now" : "Test microphone"}
          </Button>
          {testText && <span className="text-xs text-muted truncate">"{testText}"</span>}
        </div>
      </Section>

      <Section title="Processing" description="Applied in memory before transcription — audio never touches disk.">
        <Toggle label="Noise suppression" description="Reduce background noise"
          checked={a.noise_suppression} onChange={(v) => patch({ audio: { noise_suppression: v } })} />
        <Toggle label="Automatic gain control" description="Normalize quiet microphones"
          checked={a.auto_gain} onChange={(v) => patch({ audio: { auto_gain: v } })} />
        <Toggle label="Silence trimming" description="Trim leading/trailing silence for faster transcription"
          checked={a.silence_trimming} onChange={(v) => patch({ audio: { silence_trimming: v } })} />
        <Toggle label="Voice activity detection" description="Filter non-speech segments during transcription"
          checked={a.vad_enabled} onChange={(v) => patch({ audio: { vad_enabled: v } })} />
      </Section>

      <Section title="Format">
        <Select
          label="Sample rate"
          value={String(a.sample_rate)}
          onChange={(v) => patch({ audio: { sample_rate: Number(v) } })}
          options={[
            { value: "16000", label: "16 kHz — recommended for Whisper" },
            { value: "24000", label: "24 kHz" },
            { value: "44100", label: "44.1 kHz" },
            { value: "48000", label: "48 kHz" },
          ]}
        />
        <p className="text-xs text-muted mt-2">Mono · 16-bit PCM · recorded directly to memory.</p>
      </Section>
    </div>
  );
}
