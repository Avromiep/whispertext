/** First-launch setup wizard. */
import { useEffect, useState } from "react";
import {
  Mic, Keyboard, Sparkles, Check, X, ChevronRight, ChevronLeft, ShieldCheck, Loader2,
  Zap, HardDrive, ExternalLink,
} from "lucide-react";
import { api, bridge } from "../lib/api";
import { useBackendEvents } from "../lib/ws";
import { useSettings } from "../hooks/useSettings";
import { Button, Card, SecretInput, cn } from "../components/ui";

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

  // Transcription engine (the star feature — Groq cloud or fully local).
  const [engine, setEngine] = useState<"groq" | "local">("groq");
  const [groqKey, setGroqKey] = useState("");
  const [groqStatus, setGroqStatus] = useState<"idle" | "checking" | "ok" | "bad">("idle");

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

  const validateGroqKey = async () => {
    setGroqStatus("checking");
    try {
      await api.setApiKey("groq", groqKey);
      const r = await api.validateGroq();
      setGroqStatus(r.connected ? "ok" : "bad");
    } catch {
      setGroqStatus("bad");
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

  const TEST_STEP = 5;

  // The test step arms "test mode" so the real global hotkey drives the test —
  // the pipeline stops after transcription instead of typing into whatever
  // window happens to have focus during setup. Disarmed the moment this step
  // isn't showing, so the hotkey behaves normally everywhere else.
  useEffect(() => {
    if (step !== TEST_STEP) return;
    api.setTestMode(true).catch(() => {});
    return () => { api.setTestMode(false).catch(() => {}); };
  }, [step]);

  useBackendEvents((e) => {
    if (step !== TEST_STEP) return;
    if (e.type === "status") {
      if (e.state === "listening") { setTestState("recording"); setTestResult(""); }
      else if (e.state === "transcribing") setTestState("processing");
      else if (e.state === "idle") {
        setTestState((prev) => (prev === "processing" ? "done" : prev));
        setTestResult((prev) => prev || "(no speech detected — try again)");
      }
    }
    if (e.type === "test_result") {
      setTestResult(e.text || "(no speech detected — try again)");
      setTestState("done");
    }
  });

  const finish = async () => {
    await patch({
      general: { onboarding_complete: true },
      whisper: { model, engine },
      hotkeys: { push_to_talk: shortcut },
    });
  };

  const canNext = [
    /* 0 welcome    */ true,
    /* 1 permissions*/ micOk === true,
    /* 2 groq       */ engine === "local" || groqStatus === "ok",
    /* 3 model      */ true,
    /* 4 shortcut   */ true,
    /* 5 test       */ testState === "done",
    /* 6 done       */ true,
  ][step];

  const steps = [
    /* 0 — Welcome */
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

    /* 1 — Permissions */
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

    /* 2 — Instant transcription (Groq) or fully local */
    <div key="groq" className="space-y-4">
      <h2 className="text-xl font-semibold">Get instant dictation</h2>
      <p className="text-sm text-muted">
        WhisperText can transcribe the moment you release the key using a free cloud service —
        or run entirely on your computer, fully private but a bit slower.
      </p>
      <div className="grid grid-cols-1 gap-2">
        <button onClick={() => setEngine("groq")}
          className={cn("flex items-start justify-between rounded-2xl border p-4 text-left transition-all",
            engine === "groq" ? "border-accent bg-accent/10" : "border-border bg-surface hover:border-accent/40")}>
          <div className="flex items-start gap-3">
            <Zap size={18} className="text-accent shrink-0 mt-0.5" />
            <div>
              <div className="text-sm font-medium">Instant (recommended)</div>
              <div className="text-xs text-muted mt-0.5">Free, no credit card — about a minute to set up</div>
            </div>
          </div>
          {engine === "groq" && <Check size={16} className="text-accent shrink-0" />}
        </button>
        <button onClick={() => setEngine("local")}
          className={cn("flex items-start justify-between rounded-2xl border p-4 text-left transition-all",
            engine === "local" ? "border-accent bg-accent/10" : "border-border bg-surface hover:border-accent/40")}>
          <div className="flex items-start gap-3">
            <HardDrive size={18} className="text-muted shrink-0 mt-0.5" />
            <div>
              <div className="text-sm font-medium">Fully offline</div>
              <div className="text-xs text-muted mt-0.5">100% private, runs on your computer, a bit slower</div>
            </div>
          </div>
          {engine === "local" && <Check size={16} className="text-accent shrink-0" />}
        </button>
      </div>

      {engine === "groq" && (
        <Card className="space-y-3 animate-scale-in">
          <div>
            <div className="text-sm font-medium mb-1.5">Step 1 — Get your free key</div>
            <Button size="sm" onClick={() => bridge ? bridge.openExternal("https://console.groq.com/keys") : window.open("https://console.groq.com/keys")}>
              Open Groq sign-up <ExternalLink size={13} />
            </Button>
            <p className="text-xs text-muted mt-1.5">
              No credit card needed. Sign up, click "Create API Key," then copy it.
            </p>
          </div>
          <div>
            <div className="text-sm font-medium mb-1.5">Step 2 — Paste it here</div>
            <SecretInput value={groqKey} onChange={(v) => { setGroqKey(v); setGroqStatus("idle"); }} placeholder="gsk_…" />
          </div>
          <div className="flex items-center gap-3">
            <Button variant="primary" size="sm" onClick={validateGroqKey} disabled={!groqKey || groqStatus === "checking"}>
              {groqStatus === "checking" ? "Connecting…" : "Connect"}
            </Button>
            {groqStatus === "ok" && <span className="text-sm text-emerald-400 flex items-center gap-1"><Check size={14} /> Connected — you're all set!</span>}
            {groqStatus === "bad" && <span className="text-sm text-red-400 flex items-center gap-1"><X size={14} /> Couldn't connect — check the key</span>}
          </div>
        </Card>
      )}
    </div>,

    /* 3 — Speech model */
    <div key="m" className="space-y-4">
      <h2 className="text-xl font-semibold">{engine === "groq" ? "Choose an offline fallback model" : "Choose a speech model"}</h2>
      <p className="text-sm text-muted">
        {engine === "groq"
          ? "Used automatically if the cloud service is ever unreachable. Downloads on first use."
          : "Downloads automatically on first use. \"Small\" is the sweet spot for most PCs."}
      </p>
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

    /* 4 — Shortcut */
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

    /* 5 — Test */
    <div key="t" className="space-y-5 text-center">
      <h2 className="text-xl font-semibold">Test your dictation</h2>
      <p className="text-sm text-muted">
        Hold <span className="font-mono text-fg">{shortcut}</span> and speak, then release. First run downloads the model — it may take a minute.
      </p>
      <div
        aria-label="Waiting for hotkey"
        className={cn("mx-auto w-24 h-24 rounded-full flex items-center justify-center transition-all",
          testState === "recording" ? "bg-red-500 wt-glow" : "bg-accent shadow-2xl shadow-accent/40")}
      >
        {testState === "processing" ? <Loader2 size={32} className="animate-spin text-white" /> : <Mic size={32} className="text-white" />}
      </div>
      <div className="text-sm text-muted h-5">
        {testState === "idle" && `Hold ${shortcut} to start`}
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

    /* 6 — Done */
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
              {step === 0 ? "Get Started" : step === TEST_STEP && testState === "done" ? "Looks Good" : "Continue"} <ChevronRight size={15} />
            </Button>
          ) : (
            <Button variant="primary" size="lg" onClick={finish}>Launch Application</Button>
          )}
        </div>
      </div>
    </div>
  );
}
