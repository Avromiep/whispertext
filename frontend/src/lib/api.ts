/** Typed REST client for the WhisperText Python backend. */
export const API_BASE = "http://127.0.0.1:43117";
export const WS_URL = "ws://127.0.0.1:43117/ws";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try { detail = (await res.json()).message ?? detail; } catch { /* keep statusText */ }
    throw new Error(`${res.status}: ${detail}`);
  }
  return res.json() as Promise<T>;
}

export interface Settings {
  general: { theme: "dark" | "light" | "system"; launch_on_boot: boolean; notifications: boolean; telemetry: boolean; auto_update: boolean; debug_mode: boolean; onboarding_complete: boolean; font_scale: number };
  hotkeys: { push_to_talk: string; toggle_key: string; double_tap_window_ms: number; open_settings: string; hands_free_enabled: boolean; hands_free_auto_stop: boolean; hands_free_silence_ms: number };
  audio: { input_device: number | null; sample_rate: number; noise_suppression: boolean; auto_gain: boolean; silence_trimming: boolean; vad_enabled: boolean };
  whisper: { model: string; language: string; compute_device: string; beam_size: number; engine: "local" | "groq" | "deepgram"; groq_model: string; deepgram_model: string };
  ai: { enabled: boolean; mode: "cloud" | "local" | "hybrid"; provider: string; fallback_order: string[]; preset: string; custom_instructions: string; performance: "quality" | "balanced" | "speed"; minimize_costs: boolean; offline_only: boolean; streaming: boolean; retries: number; providers: Record<string, ProviderConfig> };
  typing: { method: string; chars_per_second: number; instant_paste_threshold: number; pre_type_delay_ms: number; restore_clipboard: boolean };
  formatting: { auto_capitalize: boolean; auto_punctuate: boolean; remove_fillers: boolean; smart_paragraphs: boolean; spoken_punctuation: boolean; spoken_lists: boolean };
  vocabulary: { words: string[] };
  history: { enabled: boolean; retention_days: number };
}

export interface ProviderConfig { model: string; base_url: string; temperature: number; max_tokens: number; timeout_s: number }
export interface ProviderInfo { id: string; name: string; local: boolean; needs_api_key: boolean; configured: boolean; active: boolean; config: ProviderConfig }
export interface AudioDevice { id: number; name: string; default: boolean; sample_rate: number }
export interface WhisperModelInfo { name: string; size_mb: number; ram_gb: number; accuracy: number; speed: number; installed: boolean; active: boolean; loaded: boolean; device: string | null }
export interface HistoryEntry { id: number; ts: number; app: string; raw_transcript: string; final_text: string; duration_s: number; provider: string; language: string; favorite: number }
export interface SystemInfo { version: string; hardware: { os: string; cpu: string; cpu_cores: number; ram_gb: number; gpu: string | null; vram_gb: number; cuda: boolean; accelerator: string }; recommendations: { tier: string; recommended: string; alternatives: string[]; note: string; whisper_recommendation: string }; languages: Record<string, string> }
export interface PresetInfo { label: string; description: string; prompt: string }

export const api = {
  health: () => request<{ status: string; version: string }>("/health"),
  systemInfo: () => request<SystemInfo>("/system/info"),
  systemStats: () => request<{ cpu_percent: number; memory_mb: number; history: { total: number; today: number; avg_duration_s: number }; recording: boolean }>("/system/stats"),
  getSettings: () => request<Settings>("/settings"),
  patchSettings: (patch: object) => request<Settings>("/settings", { method: "PATCH", body: JSON.stringify(patch) }),
  setApiKey: (provider: string, key: string) => request<{ ok: boolean }>("/settings/api-key", { method: "POST", body: JSON.stringify({ provider, key }) }),
  hasApiKey: (provider: string) => request<{ configured: boolean }>(`/settings/api-key/${provider}`),
  providers: () => request<ProviderInfo[]>("/providers"),
  validateProvider: (id: string) => request<{ connected: boolean; message: string; models: string[]; latency_ms: number }>(`/providers/${id}/validate`, { method: "POST" }),
  providerModels: (id: string) => request<{ models: string[] }>(`/providers/${id}/models`),
  presets: () => request<Record<string, PresetInfo>>("/presets"),
  audioDevices: () => request<AudioDevice[]>("/audio/devices"),
  dictationTest: (seconds = 4) => request<{ text: string; language: string; error?: string }>(`/dictation/test?seconds=${seconds}`, { method: "POST" }),
  dictationToggle: () => request<{ recording: boolean }>("/dictation/toggle", { method: "POST" }),
  pauseHotkeys: (paused: boolean) => request<{ paused: boolean }>(`/dictation/pause?paused=${paused}`, { method: "POST" }),
  setTestMode: (enabled: boolean) => request<{ test_mode: boolean }>(`/dictation/test-mode?enabled=${enabled}`, { method: "POST" }),
  recordHotkey: () => request<{ combo: string | null }>("/hotkeys/record", { method: "POST" }),
  history: (search = "") => request<HistoryEntry[]>(`/history?search=${encodeURIComponent(search)}`),
  favorite: (id: number, value: boolean) => request<{ ok: boolean }>(`/history/${id}/favorite?value=${value}`, { method: "POST" }),
  deleteHistory: (id: number) => request<{ ok: boolean }>(`/history/${id}`, { method: "DELETE" }),
  clearHistory: () => request<{ ok: boolean }>("/history", { method: "DELETE" }),
  models: () => request<WhisperModelInfo[]>("/models"),
  downloadModel: (name: string) => request<{ ok: boolean }>(`/models/${name}/download`, { method: "POST" }),
  deleteModel: (name: string) => request<{ ok: boolean }>(`/models/${name}`, { method: "DELETE" }),
  validateGroq: () => request<{ connected: boolean; message: string; latency_ms?: number }>("/transcription/groq/validate", { method: "POST" }),
  validateGroqBackup: () => request<{ connected: boolean; message: string; latency_ms?: number }>("/transcription/groq/validate-backup", { method: "POST" }),
  validateDeepgram: () => request<{ connected: boolean; message: string; latency_ms?: number }>("/transcription/deepgram/validate", { method: "POST" }),
  checkUpdates: () => request<{ current: string; latest: string; update_available: boolean; url: string }>("/updates/check", { method: "POST" }),
  tailLogs: (lines = 400) => request<{ text: string; shown: number; total: number }>(`/logs/tail?lines=${lines}`),
};

/** Auto-update progress as reported by the Electron main process.
 * "dev" means unpackaged builds, where the auto-updater is unavailable. */
export interface UpdateState {
  state: "idle" | "checking" | "available" | "downloading" | "ready" | "up-to-date" | "error" | "dev";
  version?: string;
  percent?: number;
  transferred?: number;
  total?: number;
  bytesPerSecond?: number;
  message?: string;
}

/** Bridge exposed by the Electron preload script (absent in plain-browser dev). */
export interface WTBridge {
  showOverlay(): void; hideOverlay(): void; openSettings(): void;
  openExternal(url: string): void; restart(): void;
  getLoginItem(): Promise<boolean>; setLoginItem(v: boolean): Promise<boolean>;
  checkUpdates(): Promise<UpdateState>;
  startUpdate(): Promise<UpdateState>;
  getUpdateState(): Promise<UpdateState>;
  installUpdate(): void;
  exportVocabulary(words: string[]): Promise<{ ok: boolean; path?: string; error?: string }>;
  importVocabulary(): Promise<{ ok?: boolean; canceled?: boolean; text?: string; path?: string; error?: string }>;
  onNavigate(cb: (page: string) => void): void;
  onUpdateState(cb: (state: UpdateState) => void): void;
}
export const bridge: WTBridge | undefined = (window as unknown as { whispertext?: WTBridge }).whispertext;
