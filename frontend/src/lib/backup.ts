/** A full backup of the user's custom data: vocabulary + text replacements.
 *  Written as one JSON file (Documents\WhisperText Backup\whispertext-backup.json
 *  in the Electron app) and restored from either page's Import button. Older
 *  vocabulary-only exports (plain text or {words:[…]}) still import cleanly. */
import type { Settings, TextReplacement } from "./api";

export interface BackupData {
  vocabulary: string[];
  text_replacements: TextReplacement[];
}

/** Gather the backup payload from the current settings. */
export function buildBackup(settings: Settings): BackupData {
  return {
    vocabulary: settings.vocabulary.words,
    text_replacements: settings.formatting.text_replacements,
  };
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

/** Parse a backup file. Accepts the combined JSON backup, a legacy
 *  vocabulary-only JSON (array or {words:[…]}), or plain text (one term/line). */
export function parseBackup(text: string): BackupData {
  let raw: unknown = null;
  try { raw = JSON.parse(text); } catch { /* not JSON — treat as line-delimited vocab */ }

  if (raw && typeof raw === "object" && !Array.isArray(raw)) {
    const o = raw as { vocabulary?: unknown; words?: unknown; text_replacements?: unknown };
    const vocab = Array.isArray(o.vocabulary) ? o.vocabulary
      : Array.isArray(o.words) ? o.words : [];
    const repl = Array.isArray(o.text_replacements) ? o.text_replacements : [];
    return { vocabulary: cleanWords(vocab), text_replacements: cleanReplacements(repl) };
  }
  if (Array.isArray(raw)) {
    return { vocabulary: cleanWords(raw), text_replacements: [] };
  }
  return { vocabulary: cleanWords(text.split(/\r?\n/)), text_replacements: [] };
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
