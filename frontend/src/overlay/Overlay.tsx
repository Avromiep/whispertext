/**
 * Recording overlay — a floating pill near the bottom of the screen.
 *
 * Visual: many thin overlapping strands forming an organic waveform (per the
 * design reference), animating continuously while listening with amplitude
 * driven by the live microphone level. Transitions through
 * Listening -> Transcribing -> Cleaning -> Typing -> fade out.
 */
import { useEffect, useRef, useState } from "react";
import { useBackendEvents, WTEvent } from "../lib/ws";
import { api, bridge } from "../lib/api";

type OverlayState = "hidden" | "listening" | "transcribing" | "cleaning" | "typing" | "done" | "empty" | "error";

const STATUS_LABEL: Record<string, string> = {
  transcribing: "Transcribing…",
  cleaning: "Cleaning…",
  typing: "Typing…",
};

const STRANDS = 14;

export default function Overlay() {
  const [state, setState] = useState<OverlayState>("hidden");
  const [elapsed, setElapsed] = useState(0);
  const [errorMsg, setErrorMsg] = useState("");
  const level = useRef(0);          // live mic level 0..1 (smoothed in draw loop)
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const startRef = useRef(0);
  const hideTimer = useRef<ReturnType<typeof setTimeout>>();
  const [dark, setDark] = useState(() => (localStorage.getItem("wt-resolved-theme") ?? "light") === "dark");

  // Mirrors App.tsx's theme resolution so the overlay matches the app even
  // though it's a separate always-on-top window — refreshed on every
  // settings change since this window is created once and never reloaded.
  const syncTheme = () => {
    api.getSettings().then((s) => {
      const theme = s.general.theme;
      const isDark = theme === "dark" ||
        (theme === "system" && window.matchMedia("(prefers-color-scheme: dark)").matches);
      setDark(isDark);
      document.documentElement.classList.toggle("dark", isDark);
      document.documentElement.classList.toggle("light", !isDark);
      localStorage.setItem("wt-resolved-theme", isDark ? "dark" : "light");
    }).catch(() => {});
  };
  useEffect(syncTheme, []);

  useBackendEvents((e: WTEvent) => {
    if (e.type === "settings_changed") {
      syncTheme();
      return;
    }
    if (e.type === "audio_level" && typeof e.level === "number") {
      level.current = e.level;
      return;
    }
    if (e.type === "error") {
      setErrorMsg(e.message ?? "Something went wrong");
      transition("error");
      hideTimer.current = setTimeout(() => transition("hidden"), 3200);
      return;
    }
    if (e.type !== "status" || !e.state) return;
    clearTimeout(hideTimer.current);
    switch (e.state) {
      case "listening":
        startRef.current = Date.now();
        setElapsed(0);
        transition("listening");
        break;
      case "transcribing":
      case "cleaning":
      case "typing":
        transition(e.state as OverlayState);
        break;
      case "done":
        transition("done");
        hideTimer.current = setTimeout(() => transition("hidden"), 700);
        break;
      case "empty":
        transition("empty");
        hideTimer.current = setTimeout(() => transition("hidden"), 1800);
        break;
      default:
        transition("hidden");
    }
  });

  function transition(next: OverlayState) {
    setState(next);
    if (next === "hidden") bridge?.hideOverlay();
    else bridge?.showOverlay();
  }

  // Recording timer
  useEffect(() => {
    if (state !== "listening") return;
    const t = setInterval(() => setElapsed((Date.now() - startRef.current) / 1000), 250);
    return () => clearInterval(t);
  }, [state]);

  // Strand waveform animation
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || state === "hidden") return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const dpr = window.devicePixelRatio || 1;
    const W = canvas.clientWidth, H = canvas.clientHeight;
    canvas.width = W * dpr;
    canvas.height = H * dpr;
    ctx.scale(dpr, dpr);

    let raf = 0;
    let smooth = 0;
    let t = 0;
    const phases = Array.from({ length: STRANDS }, (_, i) => (i / STRANDS) * Math.PI * 2);
    const strandRgb = dark ? "231, 233, 240" : "35, 32, 28";

    const draw = () => {
      t += 0.016;
      // Ease toward the live mic level; idle/processing states still breathe
      // visibly rather than sitting flat. Respond quickly to voice (fast
      // attack) so the motion reads as "alive" and reacts to speech.
      const target = state === "listening" ? Math.max(0.16, level.current) : 0.14;
      const attack = target > smooth ? 0.35 : 0.08; // fast rise, slower decay
      smooth += (target - smooth) * attack;

      ctx.clearRect(0, 0, W, H);
      const mid = H / 2;
      // Boost the vertical range and use a curve that keeps quiet speech
      // visible while still letting loud speech swing near the full canvas
      // height (tuned against the ~20.5px raw sine sum and 64px canvas).
      const energy = 0.35 + Math.pow(smooth, 0.55) * 0.95;
      for (let s = 0; s < STRANDS; s++) {
        ctx.beginPath();
        const alpha = 0.12 + 0.55 * (s / STRANDS);
        ctx.strokeStyle = `rgba(${strandRgb}, ${alpha * 0.6})`;
        ctx.lineWidth = 0.8;
        for (let x = 0; x <= W; x += 2) {
          const u = x / W;
          const edge = Math.sin(Math.PI * u); // pin strands to the endpoints
          const y =
            mid +
            edge *
              (Math.sin(u * 6.2 + t * 3.4 + phases[s]) * 10 +
                Math.sin(u * 11.7 - t * 2.6 + phases[s] * 1.7) * 7 +
                Math.sin(u * 23.1 + t * 4.8 + phases[s] * 0.6) * 3.5) *
              energy;
          if (x === 0) ctx.moveTo(x, y);
          else ctx.lineTo(x, y);
        }
        ctx.stroke();
      }
      raf = requestAnimationFrame(draw);
    };
    raf = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(raf);
  }, [state, dark]);

  if (state === "hidden") return null;

  const mmss = `${String(Math.floor(elapsed / 60)).padStart(2, "0")}:${String(Math.floor(elapsed % 60)).padStart(2, "0")}`;
  const processing = state === "transcribing" || state === "cleaning" || state === "typing";

  return (
    <div className="h-screen w-screen flex items-end justify-center pb-2">
      <div
        className={`flex items-center gap-3 rounded-2xl px-4 py-3 animate-scale-in transition-all duration-200
          shadow-[0_8px_40px_rgba(0,0,0,0.45)] border
          ${state === "error"
            ? "bg-[#2a1215] border-red-500/40"
            : "bg-elevated border-border"}`}
        style={{ width: 336 }}
      >
        {state === "error" ? (
          <>
            <span className="text-red-400 text-lg" role="img" aria-label="Error">🎤</span>
            <span className="text-sm text-red-300 truncate">{errorMsg}</span>
          </>
        ) : state === "empty" ? (
          <>
            <span className="text-muted text-lg opacity-70" role="img" aria-label="No speech">🎤</span>
            <span className="text-sm text-muted">No speech detected</span>
          </>
        ) : (
          <>
            <div className="relative shrink-0">
              <div
                className={`w-2.5 h-2.5 rounded-full transition-colors duration-300 ${
                  state === "listening" ? "bg-red-500 wt-glow"
                  : state === "done" ? "bg-emerald-500"
                  : "bg-amber-500"}`}
              />
            </div>
            <canvas ref={canvasRef} className="h-[64px] flex-1" aria-hidden="true" />
            <div className="shrink-0 w-[74px] text-right">
              {state === "listening" && (
                <span className="text-xs font-mono text-muted tabular-nums">{mmss}</span>
              )}
              {processing && (
                <span className="flex items-center justify-end gap-1.5 text-xs text-muted">
                  <span className="wt-spinner" style={{ width: 12, height: 12 }} />
                  {STATUS_LABEL[state]}
                </span>
              )}
              {state === "done" && <span className="text-xs text-emerald-600">Done ✓</span>}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
