/** WhisperText backup file: a single JSON document that can carry the user's
 *  "word data" (vocabulary, text replacements, per-app rules) and/or their "app
 *  preferences" (hotkeys, engine & model, audio, formatting toggles, theme…).
 *  Written to Documents\WhisperText Backup\whispertext-backup.json by the
 *  Electron app and restored from the Import / Export page. Older files still
 *  import: the 1.0.78 flat {vocabulary, text_replacements} shape and legacy
 *  vocabulary-only exports (a JSON array, {words:[…]}, or plain text). */
import type { Settings, TextReplacement, PerTabRule } from "./api";

/** The two user-selectable backup categories. */
export interface BackupSelection { wordData: boolean; preferences: boolean }

/** What a parsed backup file turned out to contain (empty/null where absent). */
export interface ParsedBackup {
  vocabulary: string[];
  text_replacements: TextReplacement[];
  per_tab_rules: PerTabRule[];
  preferences: Record<string, unknown> | null;
}

/** Preference sections we back up (deliberately excludes AI, API keys, history,
 *  and the word-data lists that live under `formatting`). */
const PREF_SECTIONS = ["general", "hotkeys", "audio", "whisper", "typing", "formatting"] as const;
const GENERAL_KEYS = [
  "theme", "launch_on_boot", "notifications", "auto_update", "debug_mode",
  "font_scale", "overlay_over_rdp",
] as const;
const FORMATTING_TOGGLE_KEYS = [
  "auto_capitalize", "auto_punctuate", "remove_fillers", "smart_paragraphs",
  "spoken_punctuation", "spoken_lists", "numbers_as_digits",
] as const;

function pick<T extends object, K extends keyof T>(obj: T, keys: readonly K[]): Pick<T, K> {
  const out = {} as Pick<T, K>;
  for (const k of keys) out[k] = obj[k];
  return out;
}

/** The preferences block, selected from live settings. */
function buildPreferences(s: Settings): Record<string, unknown> {
  return {
    general: pick(s.general, GENERAL_KEYS),
    hotkeys: { ...s.hotkeys },
    audio: { ...s.audio },
    whisper: { ...s.whisper },
    typing: { ...s.typing },
    formatting: pick(s.formatting, FORMATTING_TOGGLE_KEYS),
  };
}

/** Assemble the backup file for the chosen categories. */
export function buildBackup(settings: Settings, sel: BackupSelection): Record<string, unknown> {
  const file: Record<string, unknown> = { format: "whispertext-backup", version: 2 };
  if (sel.wordData) {
    file.word_data = {
      vocabulary: settings.vocabulary.words,
      text_replacements: settings.formatting.text_replacements,
      per_tab_rules: settings.formatting.per_tab_rules,
    };
  }
  if (sel.preferences) file.preferences = buildPreferences(settings);
  return file;
}

const cleanWords = (arr: unknown[]): string[] =>
  arr.map((w) => String(w).trim()).filter(Boolean);

const cleanReplacements = (arr: unknown[]): TextReplacement[] =>
  arr
    .map((r) => {
      const o = (r ?? {}) as { match?: unknown; replace?: unknown };
      return { match: String(o.match ?? "").trim(), replace: String(o.replace ?? "").trim() };
    })
    .filter((r) => r.match);

const cleanPerTabRules = (arr: unknown[]): PerTabRule[] =>
  arr
    .map((r) => {
      const o = (r ?? {}) as { match?: unknown; blank_line?: unknown };
      return { match: String(o.match ?? "").trim(), blank_line: o.blank_line !== false };
    })
    .filter((r) => r.match);

/** Keep only known preference sections (drops anything unexpected, and strips
 *  the word-data lists that must not ride in under `formatting`). */
function pickPreferences(raw: unknown): Record<string, unknown> | null {
  if (!raw || typeof raw !== "object") return null;
  const src = raw as Record<string, unknown>;
  const out: Record<string, unknown> = {};
  for (const section of PREF_SECTIONS) {
    const v = src[section];
    if (v && typeof v === "object" && !Array.isArray(v)) out[section] = { ...(v as object) };
  }
  if (out.formatting && typeof out.formatting === "object") {
    const f = out.formatting as Record<string, unknown>;
    delete f.text_replacements;   // word data, never a preference
    delete f.per_tab_rules;
  }
  return Object.keys(out).length ? out : null;
}

/** Parse any supported backup/vocabulary file into a normalized shape. */
export function parseBackup(text: string): ParsedBackup {
  const empty: ParsedBackup = { vocabulary: [], text_replacements: [], per_tab_rules: [], preferences: null };
  let raw: unknown = null;
  try { raw = JSON.parse(text); } catch { /* not JSON — treat as line-delimited vocab */ }

  // v2 structured backup: { word_data?, preferences? }
  if (raw && typeof raw === "object" && !Array.isArray(raw)
      && ("word_data" in raw || "preferences" in raw)) {
    const o = raw as { word_data?: unknown; preferences?: unknown };
    const wd = (o.word_data && typeof o.word_data === "object" ? o.word_data : {}) as Record<string, unknown>;
    return {
      vocabulary: Array.isArray(wd.vocabulary) ? cleanWords(wd.vocabulary) : [],
      text_replacements: Array.isArray(wd.text_replacements) ? cleanReplacements(wd.text_replacements) : [],
      per_tab_rules: Array.isArray(wd.per_tab_rules) ? cleanPerTabRules(wd.per_tab_rules) : [],
      preferences: pickPreferences(o.preferences),
    };
  }
  // 1.0.78 flat backup, or legacy vocabulary-only JSON ({words:[…]} or array).
  if (raw && typeof raw === "object" && !Array.isArray(raw)) {
    const o = raw as { vocabulary?: unknown; words?: unknown; text_replacements?: unknown };
    const vocab = Array.isArray(o.vocabulary) ? o.vocabulary
      : Array.isArray(o.words) ? o.words : [];
    return {
      ...empty,
      vocabulary: cleanWords(vocab),
      text_replacements: Array.isArray(o.text_replacements) ? cleanReplacements(o.text_replacements) : [],
    };
  }
  if (Array.isArray(raw)) return { ...empty, vocabulary: cleanWords(raw) };
  return { ...empty, vocabulary: cleanWords(text.split(/\r?\n/)) };
}

/** Merge imported words into the existing list, deduping case-insensitively;
 *  the imported spelling wins so an import can also correct casing. */
export function mergeVocabulary(existing: string[], incoming: string[]): string[] {
  const merged = [...existing];
  for (const w of incoming) {
    const i = merged.findIndex((x) => x.toLowerCase() === w.toLowerCase());
    if (i >= 0) merged[i] = w; else merged.push(w);
  }
  return merged;
}

/** Merge imported replacements by match phrase (case-insensitive); the
 *  imported rule wins so an import updates an existing substitution. */
export function mergeReplacements(
  existing: TextReplacement[], incoming: TextReplacement[],
): TextReplacement[] {
  const merged = [...existing];
  for (const r of incoming) {
    const i = merged.findIndex((x) => x.match.toLowerCase() === r.match.toLowerCase());
    if (i >= 0) merged[i] = r; else merged.push(r);
  }
  return merged;
}

/** Merge imported per-app rules by match (case-insensitive); imported wins. */
export function mergePerTabRules(existing: PerTabRule[], incoming: PerTabRule[]): PerTabRule[] {
  const merged = [...existing];
  for (const r of incoming) {
    const i = merged.findIndex((x) => x.match.toLowerCase() === r.match.toLowerCase());
    if (i >= 0) merged[i] = r; else merged.push(r);
  }
  return merged;
}
