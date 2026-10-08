/** Custom vocabulary: your own words that bias recognition and keep their casing. */
import { useRef, useState } from "react";
import { Download, Plus, Upload, X } from "lucide-react";
import { API_BASE, bridge } from "../lib/api";
import { buildBackup, parseBackup, mergeVocabulary, mergeReplacements } from "../lib/backup";
import { useSettings } from "../hooks/useSettings";
import { Button, PageHeader, Section } from "../components/ui";

export default function VocabularyPage() {
  const { settings, patch } = useSettings();
  const [input, setInput] = useState("");
  const [confirmWord, setConfirmWord] = useState<string | null>(null);
  const [statusMsg, setStatusMsg] = useState("");
  const fileRef = useRef<HTMLInputElement>(null);

  const flash = (msg: string) => { setStatusMsg(msg); setTimeout(() => setStatusMsg(""), 5000); };

  if (!settings) return null;
  const vocab = settings.vocabulary.words;

  const addWord = () => {
    const w = input.trim();
    if (!w) return;
    // Replace any existing case-variant so re-adding fixes the casing.
    const without = vocab.filter((x) => x.toLowerCase() !== w.toLowerCase());
    patch({ vocabulary: { words: [...without, w] } });
    setInput("");
  };
  const removeWord = (w: string) =>
    patch({ vocabulary: { words: vocab.filter((x) => x !== w) } });

  const applyImportedText = async (text: string) => {
    const data = parseBackup(text);
    const words = data.vocabulary;
    const repl = data.text_replacements;
    if (words.length === 0 && repl.length === 0) {
      flash("No vocabulary or replacements found in that file."); return;
    }
    await patch({
      vocabulary: { words: mergeVocabulary(vocab, words) },
      formatting: { text_replacements: mergeReplacements(settings.formatting.text_replacements, repl) },
    });
    const parts: string[] = [];
    if (words.length) parts.push(`${words.length} word${words.length === 1 ? "" : "s"}`);
    if (repl.length) parts.push(`${repl.length} replacement${repl.length === 1 ? "" : "s"}`);
    flash(`Imported ${parts.join(" and ")}.`);
  };

  // Save a full backup (vocabulary + text replacements) to the Documents folder
  // and reveal it (Electron); in plain browser dev, fall back to the backend
  // download endpoint.
  const exportVocab = async () => {
    if (bridge?.exportBackup) {
      const res = await bridge.exportBackup(buildBackup(settings));
      flash(res?.ok ? `Exported to ${res.path}` : "Couldn't export the backup.");
    } else {
      window.open(`${API_BASE}/backup/export`);
    }
  };

  // Open a native picker starting in Documents (Electron); browser dev uses the
  // hidden <input type=file> instead.
  const importVocab = async () => {
    if (bridge?.importBackup) {
      const res = await bridge.importBackup();
      if (res?.canceled) return;
      if (res?.ok && typeof res.text === "string") await applyImportedText(res.text);
      else flash("Couldn't read that file.");
    } else {
      fileRef.current?.click();
    }
  };

  const onImportFile = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    e.target.value = "";                     // let the same file be re-imported
    if (file) await applyImportedText(await file.text());
  };

  return (
    <div className="animate-fade-in">
      <PageHeader title="Vocabulary"
        subtitle="Your own words, names, and jargon — recognized more reliably, and typed with the exact capitalization you enter."
        actions={
          <div className="flex gap-2">
            <input ref={fileRef} type="file" accept=".txt,.json,text/plain,application/json"
              className="hidden" onChange={onImportFile} />
            <Button size="sm" onClick={importVocab} title="Restore vocabulary and text replacements from a backup file">
              <Upload size={13} /> Import
            </Button>
            <Button size="sm" onClick={exportVocab}
              title="Back up your vocabulary and text replacements to a file"
              disabled={vocab.length === 0 && settings.formatting.text_replacements.length === 0}>
              <Download size={13} /> Export
            </Button>
          </div>
        } />

      {statusMsg && (
        <div className="mb-4 text-xs text-muted bg-elevated border border-border rounded-xl px-3 py-2 animate-fade-in break-all">
          {statusMsg}
        </div>
      )}

      <Section title="Your words"
        description="Add a term and press Enter. Whatever capitalization you type is how it'll be typed out — e.g. GitHub, OAuth, kubectl, iPhone.">
        <div className="flex gap-2">
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); addWord(); } }}
            placeholder="Add a word or phrase…"
            aria-label="Add vocabulary word"
            className="flex-1 h-9 rounded-xl bg-elevated border border-border px-3 text-sm placeholder:text-muted/60 focus:border-accent transition-colors"
          />
          <Button size="sm" onClick={addWord} disabled={!input.trim()}>
            <Plus size={13} /> Add
          </Button>
        </div>
        {vocab.length === 0 ? (
          <p className="text-xs text-muted mt-3">No custom words yet.</p>
        ) : (
          <div className="flex flex-wrap gap-2 mt-3">
            {vocab.map((w) => (
              <span key={w}
                className="inline-flex items-center gap-1.5 rounded-lg bg-elevated border border-border pl-2.5 pr-1.5 py-1 text-sm font-medium">
                {w}
                <button aria-label={`Remove ${w}`} onClick={() => setConfirmWord(w)}
                  className="text-muted hover:text-red-400 transition-colors">
                  <X size={13} />
                </button>
              </span>
            ))}
          </div>
        )}
      </Section>

      {confirmWord !== null && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 animate-fade-in"
          onClick={() => setConfirmWord(null)}
          onKeyDown={(e) => { if (e.key === "Escape") setConfirmWord(null); }}
          role="dialog" aria-modal="true" aria-label="Confirm removing word"
        >
          <div className="bg-surface border border-border rounded-2xl p-5 max-w-xs mx-4 shadow-xl animate-scale-in"
            onClick={(e) => e.stopPropagation()}>
            <div className="text-sm font-medium mb-1">Remove word?</div>
            <p className="text-xs text-muted mb-4">
              Remove “<span className="font-medium text-fg">{confirmWord}</span>” from your vocabulary?
            </p>
            <div className="flex justify-end gap-2">
              <Button size="sm" variant="ghost" autoFocus onClick={() => setConfirmWord(null)}>No</Button>
              <Button size="sm" variant="danger" onClick={() => { removeWord(confirmWord); setConfirmWord(null); }}>
                Yes, remove
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
