import { useCallback, useEffect, useState } from "react";
import {
  Home, Mic, BookOpen, Sparkles, Volume2, Keyboard, HistoryIcon, Package, Wrench, Info,
} from "lucide-react";
import { SettingsContext, useSettingsProvider } from "./hooks/useSettings";
import { useBackendEvents, WTEvent } from "./lib/ws";
import { bridge } from "./lib/api";
import { cn, WiggleText } from "./components/ui";
import CommandPalette from "./components/CommandPalette";
import Onboarding from "./pages/Onboarding";
import HomePage from "./pages/HomePage";
import DictationPage from "./pages/DictationPage";
import VocabularyPage from "./pages/VocabularyPage";
import AIPage from "./pages/AIPage";
import AudioPage from "./pages/AudioPage";
import HotkeysPage from "./pages/HotkeysPage";
import HistoryPage from "./pages/HistoryPage";
import ModelsPage from "./pages/ModelsPage";
import AdvancedPage from "./pages/AdvancedPage";
import AboutPage from "./pages/AboutPage";

export type PageId =
  | "home" | "dictation" | "vocabulary" | "ai" | "audio" | "hotkeys"
  | "history" | "models" | "advanced" | "about";

const NAV: { id: PageId; label: string; icon: typeof Home }[] = [
  { id: "home", label: "Home", icon: Home },
  { id: "dictation", label: "Dictation", icon: Mic },
  { id: "vocabulary", label: "Vocabulary", icon: BookOpen },
  { id: "ai", label: "AI", icon: Sparkles },
  { id: "audio", label: "Audio", icon: Volume2 },
  { id: "hotkeys", label: "Hotkeys", icon: Keyboard },
  { id: "history", label: "History", icon: HistoryIcon },
  { id: "models", label: "Models", icon: Package },
  { id: "advanced", label: "Advanced", icon: Wrench },
  { id: "about", label: "About", icon: Info },
];

interface Toast { id: number; message: string; kind: string }
let toastSeq = 0;

export default function App() {
  const ctx = useSettingsProvider();
  const [page, setPage] = useState<PageId>("home");
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [toasts, setToasts] = useState<Toast[]>([]);
  const [status, setStatus] = useState("idle");

  const pushToast = useCallback((message: string, kind = "info") => {
    const id = ++toastSeq;
    setToasts((t) => [...t.slice(-3), { id, message, kind }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 3500);
  }, []);

  useBackendEvents(
    useCallback((e: WTEvent) => {
      if (e.type === "status" && e.state) setStatus(e.state);
      if (e.type === "notification" && e.message) pushToast(e.message, e.kind ?? "info");
      if (e.type === "error" && e.message) pushToast(e.message, "error");
      if (e.type === "settings_changed") ctx.reload();
      // Native desktop notification when the window isn't visible.
      if ((e.type === "notification" || e.type === "error") && e.message &&
          document.hidden && ctx.settings?.general.notifications &&
          Notification.permission !== "denied") {
        new Notification("WhisperText", { body: e.message, silent: true });
      }
    }, [pushToast, ctx]),
  );

  // Theme + font scale
  useEffect(() => {
    const theme = ctx.settings?.general.theme ?? "light";
    const dark = theme === "dark" ||
      (theme === "system" && window.matchMedia("(prefers-color-scheme: dark)").matches);
    document.documentElement.classList.toggle("dark", dark);
    document.documentElement.classList.toggle("light", !dark);
    // Cache the resolved theme so next launch can apply it synchronously
    // before first paint (see the inline script in index.html) instead of
    // flashing the wrong theme while settings load from the backend.
    localStorage.setItem("wt-resolved-theme", dark ? "dark" : "light");
    document.documentElement.style.setProperty(
      "--font-scale", String(ctx.settings?.general.font_scale ?? 1));
  }, [ctx.settings?.general.theme, ctx.settings?.general.font_scale]);

  // Keyboard-first: Ctrl+K command palette, Ctrl+1..9 page jumps
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.ctrlKey && e.key.toLowerCase() === "k") { e.preventDefault(); setPaletteOpen((v) => !v); }
      if (e.ctrlKey && /^[1-9]$/.test(e.key)) {
        const target = NAV[Number(e.key) - 1];
        if (target) { e.preventDefault(); setPage(target.id); }
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  useEffect(() => { bridge?.onNavigate((p) => setPage(p as PageId)); }, []);

  if (ctx.settings && !ctx.settings.general.onboarding_complete) {
    return (
      <SettingsContext.Provider value={ctx}>
        <Onboarding />
      </SettingsContext.Provider>
    );
  }

  const STATUS_BADGE: Record<string, { label: string; cls: string }> = {
    idle: { label: "Ready", cls: "bg-emerald-500" },
    listening: { label: "Listening", cls: "bg-sky-500" },
    transcribing: { label: "Processing", cls: "bg-amber-500" },
    cleaning: { label: "AI Cleaning", cls: "bg-violet-500" },
    typing: { label: "Typing", cls: "bg-emerald-500" },
    done: { label: "Ready", cls: "bg-emerald-500" },
    empty: { label: "Ready", cls: "bg-emerald-500" },
    error: { label: "Error", cls: "bg-red-500" },
  };
  const badge = STATUS_BADGE[status] ?? STATUS_BADGE.idle;

  return (
    <SettingsContext.Provider value={ctx}>
      <div className="flex h-full">
        {/* Sidebar */}
        <aside className="w-52 shrink-0 border-r border-border bg-surface/60 flex flex-col">
          <div className="px-4 py-4 flex items-center gap-2.5">
            <img src="icon.png" alt="" className="w-7 h-7 rounded-lg shadow-lg shadow-accent/30" />
            <span className="font-semibold tracking-tight">WhisperText</span>
          </div>
          <nav className="flex-1 px-2 space-y-0.5" aria-label="Main navigation">
            {NAV.map(({ id, label, icon: Icon }, i) => (
              <button
                key={id}
                onClick={() => setPage(id)}
                className={cn(
                  "wt-wiggle-area w-full flex items-center gap-2.5 rounded-xl px-3 py-2 text-sm transition-colors duration-150",
                  page === id ? "bg-elevated text-fg font-medium" : "text-muted hover:text-fg hover:bg-elevated/50",
                )}
                title={i < 9 ? `Ctrl+${i + 1}` : undefined}
              >
                <Icon size={15} /> <WiggleText>{label}</WiggleText>
              </button>
            ))}
          </nav>
          <div className="p-3 border-t border-border flex items-center gap-2 text-xs text-muted">
            <span className={cn("w-2 h-2 rounded-full", badge.cls, !ctx.backendUp && "bg-red-500")} />
            {ctx.backendUp ? badge.label : "Backend starting…"}
          </div>
        </aside>

        {/* Content */}
        <main className="flex-1 overflow-y-auto">
          <div className="max-w-3xl mx-auto px-8 py-8" key={page}>
            {page === "home" && <HomePage go={setPage} />}
            {page === "dictation" && <DictationPage />}
            {page === "vocabulary" && <VocabularyPage />}
            {page === "ai" && <AIPage />}
            {page === "audio" && <AudioPage />}
            {page === "hotkeys" && <HotkeysPage />}
            {page === "history" && <HistoryPage />}
            {page === "models" && <ModelsPage />}
            {page === "advanced" && <AdvancedPage />}
            {page === "about" && <AboutPage />}
          </div>
        </main>
      </div>

      <CommandPalette open={paletteOpen} onClose={() => setPaletteOpen(false)} go={setPage} notify={pushToast} />

      {/* Toasts */}
      <div className="fixed bottom-4 right-4 space-y-2 z-50" role="status" aria-live="polite">
        {toasts.map((t) => (
          <div
            key={t.id}
            className={cn(
              "animate-slide-up rounded-xl border px-4 py-2.5 text-sm shadow-xl backdrop-blur bg-surface/95",
              t.kind === "error" ? "border-red-500/40 text-red-300"
              : t.kind === "warning" ? "border-amber-500/40 text-amber-300"
              : "border-border",
            )}
          >
            {t.message}
          </div>
        ))}
      </div>
    </SettingsContext.Provider>
  );
}
