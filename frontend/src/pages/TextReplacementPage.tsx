/** Text Replacement: user substitutions applied to the transcript, e.g. "gonna" -> "going to". */
import { useState } from "react";
import { Archive, ArrowRight, Plus, X } from "lucide-react";
import type { PageId } from "../App";
import { useSettings } from "../hooks/useSettings";
import { Button, PageHeader, Section } from "../components/ui";

export default function TextReplacementPage({ go }: { go: (p: PageId) => void }) {
  const { settings, patch } = useSettings();
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [confirmMatch, setConfirmMatch] = useState<string | null>(null);

  if (!settings) return null;
  const rules = settings.formatting.text_replacements;

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
          <Button size="sm" variant="ghost" onClick={() => go("backup")}
            title="Back up or restore your replacements and more">
            <Archive size={13} /> Import / Export
          </Button>
        } />

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
