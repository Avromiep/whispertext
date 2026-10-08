/** Text Replacement: user substitutions applied to the transcript, e.g. "gonna" -> "going to". */
import { useRef, useState } from "react";
import { ArrowRight, Download, Plus, Upload, X } from "lucide-react";
import { API_BASE, bridge } from "../lib/api";
import { buildBackup, parseBackup, mergeVocabulary, mergeReplacements } from "../lib/backup";
import { useSettings } from "../hooks/useSettings";
import { Button, PageHeader, Section } from "../components/ui";

export default function TextReplacementPage() {
  const { settings, patch } = useSettings();
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [confirmMatch, setConfirmMatch] = useState<string | null>(null);
  const [statusMsg, setStatusMsg] = useState("");
  const fileRef = useRef<HTMLInputElement>(null);

  const flash = (msg: string) => { setStatusMsg(msg); setTimeout(() => setStatusMsg(""), 5000); };

  if (!settings) return null;
  const rules = settings.formatting.text_replacements;

  // Export/import a full backup (vocabulary + text replacements) — the same
  // backup the Vocabulary page produces, reachable from here too.
  const applyImportedText = async (text: string) => {
    const data = parseBackup(text);
    if (data.vocabulary.length === 0 && data.text_replacements.length === 0) {
      flash("No vocabulary or replacements found in that file."); return;
    }
    await patch({
      vocabulary: { words: mergeVocabulary(settings.vocabulary.words, data.vocabulary) },
      formatting: { text_replacements: mergeReplacements(rules, data.text_replacements) },
    });
    const parts: string[] = [];
    if (data.vocabulary.length) parts.push(`${data.vocabulary.length} word${data.vocabulary.length === 1 ? "" : "s"}`);
    if (data.text_replacements.length) parts.push(`${data.text_replacements.length} replacement${data.text_replacements.length === 1 ? "" : "s"}`);
    flash(`Imported ${parts.join(" and ")}.`);
  };

  const exportBackup = async () => {
    if (bridge?.exportBackup) {
      const res = await bridge.exportBackup(buildBackup(settings));
      flash(res?.ok ? `Exported to ${res.path}` : "Couldn't export the backup.");
    } else {
      window.open(`${API_BASE}/backup/export`);
    }
  };

  const importBackup = async () => {
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
    e.target.value = "";
    if (file) await applyImportedText(await file.text());
  };

  const add = () => {
    const match = from.trim();
    if (!match) return;
    // Replace any existing rule for the same phrase (case-insensitive), so
    // re-adding updates it instead of duplicating.
    const without = rules.filter((r) => r.match.toLowerCase() !== match.toLowerCase());
    patch({ formatting: { text_replacements: [...without, { match, replace: to.trim() }] } });
    setFrom("");
    setTo("");
  };

  const remove = (match: string) =>
    patch({ formatting: { text_replacements: rules.filter((r) => r.match !== match) } });

  return (
    <div className="animate-fade-in">
      <PageHeader title="Text Replacement"
        subtitle="Automatically swap a word or phrase for another as you dictate — say the left, get the right. Matching ignores case and keeps your capitalization (so “Gonna” at a sentence start becomes “Going to”)."
        actions={
          <div className="flex gap-2">
            <input ref={fileRef} type="file" accept=".txt,.json,text/plain,application/json"
              className="hidden" onChange={onImportFile} />
            <Button size="sm" onClick={importBackup} title="Restore vocabulary and text replacements from a backup file">
              <Upload size={13} /> Import
            </Button>
            <Button size="sm" onClick={exportBackup}
              title="Back up your vocabulary and text replacements to a file"
              disabled={rules.length === 0 && settings.vocabulary.words.length === 0}>
              <Download size={13} /> Export
            </Button>
          </div>
        } />

      {statusMsg && (
        <div className="mb-4 text-xs text-muted bg-elevated border border-border rounded-xl px-3 py-2 animate-fade-in break-all">
          {statusMsg}
        </div>
      )}

      <Section title="Replacements"
        description="For example: “gonna” → “going to”, “omw” → “on my way”, “teh” → “the”. Matches whole words only; leave the right side blank to simply delete the word.">
        <div className="flex items-center gap-2">
          <input
            value={from}
            onChange={(e) => setFrom(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); add(); } }}
            placeholder="When I say…"
            aria-label="Phrase to replace"
            className="flex-1 h-9 rounded-xl bg-elevated border border-border px-3 text-sm placeholder:text-muted/60 focus:border-accent transition-colors"
          />
          <ArrowRight size={15} className="text-muted shrink-0" />
          <input
            value={to}
            onChange={(e) => setTo(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); add(); } }}
            placeholder="Type this instead…"
            aria-label="Replacement text"
            className="flex-1 h-9 rounded-xl bg-elevated border border-border px-3 text-sm placeholder:text-muted/60 focus:border-accent transition-colors"
          />
          <Button size="sm" onClick={add} disabled={!from.trim()}>
            <Plus size={13} /> Add
          </Button>
        </div>

        {rules.length === 0 ? (
          <p className="text-xs text-muted mt-3">No replacements yet.</p>
        ) : (
          <div className="mt-3 space-y-1.5">
            {rules.map((r) => (
              <div key={r.match}
                className="flex items-center gap-2 rounded-xl bg-elevated border border-border px-3 py-2 text-sm">
                <span className="font-medium truncate max-w-[40%]">{r.match}</span>
                <ArrowRight size={14} className="text-muted shrink-0" />
                <span className="flex-1 truncate">
                  {r.replace ? r.replace : <em className="text-muted">(deleted)</em>}
                </span>
                <button aria-label={`Remove ${r.match}`} onClick={() => setConfirmMatch(r.match)}
                  className="text-muted hover:text-red-400 transition-colors shrink-0">
                  <X size={14} />
                </button>
              </div>
            ))}
          </div>
        )}
      </Section>

      {confirmMatch !== null && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 animate-fade-in"
          onClick={() => setConfirmMatch(null)}
          onKeyDown={(e) => { if (e.key === "Escape") setConfirmMatch(null); }}
          role="dialog" aria-modal="true" aria-label="Confirm removing replacement"
        >
          <div className="bg-surface border border-border rounded-2xl p-5 max-w-xs mx-4 shadow-xl animate-scale-in"
            onClick={(e) => e.stopPropagation()}>
            <div className="text-sm font-medium mb-1">Remove replacement?</div>
            <p className="text-xs text-muted mb-4">
              Are you sure you want to remove “<span className="font-medium text-fg">{confirmMatch}</span>”?
            </p>
            <div className="flex justify-end gap-2">
              <Button size="sm" variant="ghost" autoFocus onClick={() => setConfirmMatch(null)}>No</Button>
              <Button size="sm" variant="danger" onClick={() => { remove(confirmMatch); setConfirmMatch(null); }}>
                Yes, remove
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
