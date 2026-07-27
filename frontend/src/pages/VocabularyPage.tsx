/** Custom vocabulary: your own words that bias recognition and keep their casing. */
import { useState } from "react";
import { Plus, X } from "lucide-react";
import { useSettings } from "../hooks/useSettings";
import { Button, PageHeader, Section } from "../components/ui";

export default function VocabularyPage() {
  const { settings, patch } = useSettings();
  const [input, setInput] = useState("");
  const [confirmWord, setConfirmWord] = useState<string | null>(null);

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

  return (
    <div className="animate-fade-in">
      <PageHeader title="Vocabulary"
        subtitle="Your own words, names, and jargon — recognized more reliably, and typed with the exact capitalization you enter." />

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
