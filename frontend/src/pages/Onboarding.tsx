/** First-launch setup wizard — 8 steps per spec. */
import { useEffect, useState } from "react";
import {
  Mic, Keyboard, Sparkles, Check, X, ChevronRight, ChevronLeft, ShieldCheck, Loader2,
} from "lucide-react";
import { api } from "../lib/api";
import { useSettings } from "../hooks/useSettings";
import { Button, Card, SecretInput, cn } from "../components/ui";

const PROVIDERS = [
  { id: "openai", name: "OpenAI", desc: "GPT models — fast and reliable" },
  { id: "anthropic", name: "Anthropic", desc: "Claude models — excellent writing" },
  { id: "gemini", name: "Google", desc: "Gemini — generous free tier" },
  { id: "openrouter", name: "OpenRouter", desc: "One key, hundreds of models" },
  { id: "ollama", name: "Ollama", desc: "100% local and private" },
];

const MODELS = [
  { id: "tiny", stars: 2, speed: "Fastest", ram: "1 GB RAM" },
  { id: "base", stars: 3, speed: "Very fast", ram: "1 GB RAM" },
  { id: "small", stars: 4, speed: "Very fast", ram: "2 GB RAM" },
  { id: "medium", stars: 4.5, speed: "Moderate", ram: "5 GB RAM" },
  { id: "large-v3", stars: 5, speed: "Slower", ram: "10 GB RAM" },
];

export default function Onboarding() {
  const { patch } = useSettings();
  const [step, setStep] = useState(0);
  const [provider, setProvider] = useState("openai");
  const [apiKey, setApiKey] = useState("");
  const [keyStatus, setKeyStatus] = useState<"idle" | "checking" | "ok" | "bad">("idle");
  const [model, setModel] = useState("small");
  const [micOk, setMicOk] = useState<boolean | null>(null);
  const [shortcut, setShortcut] = useState("windows+shift");
  const [recordingShortcut, setRecordingShortcut] = useState(false);
  const [testState, setTestState] = useState<"idle" | "recording" | "processing" | "done">("idle");
  const [testResult, setTestResult] = useState("");

  // Step 2: microphone permission/availability check
  useEffect(() => {
    if (step !== 1) return;
    api.audioDevices()
      .then((d) => setMicOk(d.length > 0))
      .catch(() => setMicOk(false));
  }, [step]);

  const validateKey = async () => {
    setKeyStatus("checking");
    try {
      await api.setApiKey(provider, apiKey);
      const r = await api.validateProvider(provider);
      setKeyStatus(r.connected ? "ok" : "bad");
    } catch {
      setKeyStatus("bad");
    }
  };

  const recordShortcut = async () => {
    setRecordingShortcut(true);
    try {
      const r = await api.recordHotkey();
      if (r.combo) setShortcut(r.combo);
    } finally {
      setRecordingShortcut(false);
    }
  };

  const runTest = async () => {
    setTestState("recording");
    try {
      const p = api.dictationTest(4);
      setTimeout(() => setTestState("processing"), 4100);
      const r = await p;
      setTestResult(r.text || "(no speech detected — try again)");
      setTestState("done");
    } catch (e) {
      setTestResult(`Test failed: ${e}`);
      setTestState("done");
    }
  };

  const finish = async () => {
    await patch({
      general: { onboarding_complete: true },
      ai: { provider },
      whisper: { model },
      hotkeys: { push_to_talk: shortcut },
    });
  };

  const needsKey = provider !== "ollama";
  const canNext = [
    true,
    micOk === true,
    true,
    !needsKey || keyStatus === "ok",
    true,
    true,
    testState === "done",
    true,
  ][step];

  const steps = [
    /* 1 — Welcome */
    <div key="w" className="text-center space-y-6">
      <div className="mx-auto w-16 h-16 rounded-2xl bg-accent flex items-center justify-center shadow-2xl shadow-accent/40">
        <Mic size={28} className="text-white" />
      </div>
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Welcome to WhisperText</h1>
        <p className="text-muted mt-2">Your AI voice assistant for every application.</p>
      </div>
      <div className="flex items-center justify-center gap-3 text-muted text-sm">
        <Keyboard size={16} /> <ChevronRight size={13} />
        <Mic size={16} /> <ChevronRight size={13} />
        <Sparkles size={16} /> <ChevronRight size={13} />
        <span className="font-medium text-fg">Perfect text</span>
      </div>
      <p className="text-sm text-muted max-w-sm mx-auto">
        Hold a shortcut, speak naturally, release — polished text appears wherever your cursor is. In any app.
      </p>
    </div>,

    /* 2 — Permissions */
    <div key="p" className="space-y-4">
      <h2 className="text-xl font-semibold">Permissions</h2>
      <p className="text-sm text-muted">WhisperText needs your microphone and keyboard access to work everywhere.</p>
      {[
        { label: "Microphone", ok: micOk },
        { label: "Global keyboard hook", ok: true },
        { label: "Simulated typing", ok: true },
      ].map((perm) => (
        <Card key={perm.label} className="flex items-center justify-between !p-4">
          <span className="text-sm font-medium flex items-center gap-2"><ShieldCheck size={15} className="text-muted" />{perm.label}</span>
          {perm.ok === null ? <Loader2 size={16} className="animate-spin text-muted" />
            : perm.ok ? <Check size={16} className="text-emerald-400" />
            : <X size={16} className="text-red-400" />}
        </Card>
      ))}
      {micOk === false && (
        <p className="text-xs text-red-400">No microphone detected. Connect one, then
          <button className="underline ml-1" onClick={() => api.audioDevices().then((d) => setMicOk(d.length > 0))}>retry</button>.
        </p>
      )}
    </div>,

    /* 3 — Provider */
    <div key="prov" className="space-y-4">
      <h2 className="text-xl font-semibold">Choose your AI provider</h2>
      <p className="text-sm text-muted">Cleans up your transcriptions. You can change this anytime.</p>
      <div className="grid grid-cols-1 gap-2">
        {PROVIDERS.map((p) => (
          <button key={p.id} onClick={() => { setProvider(p.id); setKeyStatus("idle"); }}
            className={cn("flex items-center justify-between rounded-2xl border p-4 text-left transition-all",
              provider === p.id ? "border-accent bg-accent/10" : "border-border bg-surface hover:border-accent/40")}>
            <div>
              <div className="text-sm font-medium">{p.name}</div>
              <div className="text-xs text-muted">{p.desc}</div>
            </div>
            {provider === p.id && <Check size={16} className="text-accent" />}
          </button>
        ))}
      </div>
    </div>,

    /* 4 — API Key */
    <div key="key" className="space-y-4">
      <h2 className="text-xl font-semibold">{needsKey ? "Enter your API key" : "Local AI — no key needed"}</h2>
      {needsKey ? (
        <>
          <p className="text-sm text-muted">Stored securely in Windows Credential Manager — never in plain text.</p>
          <SecretInput label={`${provider} API key`} value={apiKey} onChange={(v) => { setApiKey(v); setKeyStatus("idle"); }}
            placeholder="sk-…" />
          <div className="flex items-center gap-3">
            <Button variant="primary" size="sm" onClick={validateKey} disabled={!apiKey || keyStatus === "checking"}>
              {keyStatus === "checking" ? "Validating…" : "Validate key"}
            </Button>
            {keyStatus === "ok" && <span className="text-sm text-emerald-400 flex items-center gap-1"><Check size={14} /> Connected</span>}
            {keyStatus === "bad" && <span className="text-sm text-red-400 flex items-center gap-1"><X size={14} /> Invalid API key</span>}
          </div>
        </>
      ) : (
        <p className="text-sm text-muted">
          Ollama runs entirely on your machine. Make sure it's installed and running — we'll auto-detect your models.
        </p>
      )}
    </div>,

    /* 5 — Speech model */
    <div key="m" className="space-y-4">
      <h2 className="text-xl font-semibold">Choose a speech model</h2>
      <p className="text-sm text-muted">Downloads automatically on first use. "Small" is the sweet spot for most PCs.</p>
      <div className="space-y-2">
        {MODELS.map((m) => (
          <button key={m.id} onClick={() => setModel(m.id)}
            className={cn("w-full flex items-center justify-between rounded-2xl border p-4 text-left transition-all",
              model === m.id ? "border-accent bg-accent/10" : "border-border bg-surface hover:border-accent/40")}>
            <div className="flex items-center gap-3">
              <span className="text-sm font-medium capitalize w-20">{m.id}</span>
              <span className="text-amber-400 text-xs">{"⭐".repeat(Math.round(m.stars))}</span>
            </div>
            <div className="text-xs text-muted">{m.speed} · {m.ram}</div>
          </button>
        ))}
      </div>
    </div>,

    /* 6 — Shortcut */
    <div key="s" className="space-y-4 text-center">
      <h2 className="text-xl font-semibold">Choose your shortcut</h2>
      <p className="text-sm text-muted">Hold to talk, release to type. Double-tap Right Ctrl toggles hands-free mode.</p>
      <div className="py-6">
        <div className={cn("mx-auto w-fit rounded-2xl border-2 px-8 py-4 font-mono text-lg transition-all",
          recordingShortcut ? "border-accent animate-pulse" : "border-border bg-surface")}>
          {recordingShortcut ? "Press your desired shortcut…" : shortcut}
        </div>
      </div>
      <Button onClick={recordShortcut} disabled={recordingShortcut}>Record new shortcut</Button>
    </div>,

    /* 7 — Test */
    <div key="t" className="space-y-5 text-center">
      <h2 className="text-xl font-semibold">Test your dictation</h2>
      <p className="text-sm text-muted">Click the mic and speak for a few seconds. First run downloads the model — it may take a minute.</p>
      <button
        onClick={runTest}
        disabled={testState === "recording" || testState === "processing"}
        aria-label="Start test recording"
        className={cn("mx-auto w-24 h-24 rounded-full flex items-center justify-center transition-all",
          testState === "recording" ? "bg-red-500 wt-glow" : "bg-accent hover:brightness-110 shadow-2xl shadow-accent/40")}
      >
        {testState === "processing" ? <Loader2 size={32} className="animate-spin text-white" /> : <Mic size={32} className="text-white" />}
      </button>
      <div className="text-sm text-muted h-5">
        {testState === "recording" && "Listening… speak now"}
        {testState === "processing" && "Transcribing…"}
      </div>
      {testState === "done" && (
        <Card className="text-left animate-scale-in">
          <div className="text-xs text-muted mb-1">Transcription</div>
          <div className="text-sm">{testResult}</div>
        </Card>
      )}
    </div>,

    /* 8 — Done */
    <div key="d" className="text-center space-y-6">
      <div className="mx-auto w-20 h-20 rounded-full bg-emerald-500/15 border border-emerald-500/40 flex items-center justify-center animate-scale-in">
        <Check size={36} className="text-emerald-400" />
      </div>
      <h1 className="text-2xl font-semibold">You're ready to dictate anywhere.</h1>
      <p className="text-sm text-muted max-w-sm mx-auto">
        Hold <span className="font-mono text-fg">{shortcut}</span> and speak in any app.
        WhisperText lives in your system tray.
      </p>
    </div>,
  ];

  return (
    <div className="h-full flex items-center justify-center p-8">
      <div className="w-full max-w-lg">
        {/* Progress dots */}
        <div className="flex justify-center gap-1.5 mb-10">
          {steps.map((_, i) => (
            <div key={i} className={cn("h-1.5 rounded-full transition-all duration-300",
              i === step ? "w-6 bg-accent" : i < step ? "w-1.5 bg-accent/60" : "w-1.5 bg-border")} />
          ))}
        </div>

        <div key={step} className="animate-slide-up min-h-[340px]">{steps[step]}</div>

        <div className="flex justify-between mt-10">
          {step > 0 ? (
            <Button variant="ghost" onClick={() => setStep(step - 1)}><ChevronLeft size={15} /> Back</Button>
          ) : <div />}
          {step < steps.length - 1 ? (
            <Button variant="primary" onClick={() => setStep(step + 1)} disabled={!canNext}>
              {step === 0 ? "Get Started" : step === 6 && testState === "done" ? "Looks Good" : "Continue"} <ChevronRight size={15} />
            </Button>
          ) : (
            <Button variant="primary" size="lg" onClick={finish}>Launch Application</Button>
          )}
        </div>
      </div>
    </div>
  );
}
