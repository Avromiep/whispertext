/** Dictation settings: formatting, typing behavior, language, cleanup toggles. */
import { api, } from "../lib/api";
import { useEffect, useState } from "react";
import { Plus, X } from "lucide-react";
import { useSettings } from "../hooks/useSettings";
import { Button, PageHeader, Section, Select, Slider, Toggle } from "../components/ui";

export default function DictationPage() {
  const { settings, patch } = useSettings();
  const [languages, setLanguages] = useState<Record<string, string>>({ auto: "Auto-detect" });
  const [vocabInput, setVocabInput] = useState("");

  useEffect(() => {
    api.systemInfo().then((i) => setLanguages(i.languages)).catch(() => {});
  }, []);

  if (!settings) return null;
  const f = settings.formatting;
  const t = settings.typing;
  const vocab = settings.vocabulary.words;

  const addWord = () => {
    const w = vocabInput.trim();
    if (!w) return;
    // Replace any existing case-variant so re-adding fixes the casing.
    const without = vocab.filter((x) => x.toLowerCase() !== w.toLowerCase());
    patch({ vocabulary: { words: [...without, w] } });
    setVocabInput("");
  };
  const removeWord = (w: string) =>
    patch({ vocabulary: { words: vocab.filter((x) => x !== w) } });

  return (
    <div className="animate-fade-in">
      <PageHeader title="Dictation" subtitle="How your speech becomes text." />

      <Section title="Language" description="Whisper detects the language automatically, or you can pin one.">
        <Select
          value={settings.whisper.language}
          onChange={(v) => patch({ whisper: { language: v } })}
          options={Object.entries(languages).map(([value, label]) => ({ value, label }))}
          label="Spoken language"
        />
      </Section>

      <Section title="Vocabulary"
        description="Your own words, names, and jargon. They're recognized more reliably, and typed with the exact capitalization you enter here — e.g. GitHub, OAuth, kubectl.">
        <div className="flex gap-2">
          <input
            value={vocabInput}
            onChange={(e) => setVocabInput(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); addWord(); } }}
            placeholder="Add a word or phrase…"
            aria-label="Add vocabulary word"
            className="flex-1 h-9 rounded-xl bg-elevated border border-border px-3 text-sm placeholder:text-muted/60 focus:border-accent transition-colors"
          />
          <Button size="sm" onClick={addWord} disabled={!vocabInput.trim()}>
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
                <button aria-label={`Remove ${w}`} onClick={() => removeWord(w)}
                  className="text-muted hover:text-red-400 transition-colors">
                  <X size={13} />
                </button>
              </span>
            ))}
          </div>
        )}
      </Section>

      <Section title="Cleanup & formatting" description="Applied by the AI cleanup stage.">
        <Toggle label="Automatically capitalize" description="Sentence-start capitalization"
          checked={f.auto_capitalize} onChange={(v) => patch({ formatting: { auto_capitalize: v } })} />
        <Toggle label="Automatically punctuate" description="Add commas, periods, and question marks"
          checked={f.auto_punctuate} onChange={(v) => patch({ formatting: { auto_punctuate: v } })} />
        <Toggle label="Remove filler words" description={'Strip "um", "uh", "like", false starts'}
          checked={f.remove_fillers} onChange={(v) => patch({ formatting: { remove_fillers: v } })} />
        <Toggle label="Smart paragraph detection" description="Break paragraphs at topic changes"
          checked={f.smart_paragraphs} onChange={(v) => patch({ formatting: { smart_paragraphs: v } })} />
        <Toggle label="Spoken punctuation" description={'"comma" → , · "new paragraph" → line break'}
          checked={f.spoken_punctuation} onChange={(v) => patch({ formatting: { spoken_punctuation: v } })} />
        <Toggle label="Spoken lists" description={'"bullet point" → • · "number one" → 1.'}
          checked={f.spoken_lists} onChange={(v) => patch({ formatting: { spoken_lists: v } })} />
      </Section>

      <Section title="Typing" description="How the final text is inserted at your cursor.">
        <Select
          value={t.method}
          onChange={(v) => patch({ typing: { method: v } })}
          options={[
            { value: "auto", label: "Auto (recommended) — keystrokes, paste for long text" },
            { value: "keystrokes", label: "Always simulate keystrokes" },
            { value: "clipboard", label: "Always paste via clipboard" },
          ]}
          label="Insertion method"
        />
        <div className="mt-4 space-y-3">
          <Slider label="Typing speed" min={50} max={1000} step={25} value={t.chars_per_second}
            format={(v) => `${v} chars/s`} onChange={(v) => patch({ typing: { chars_per_second: v } })} />
          <Slider label="Instant-paste threshold" min={0} max={1000} step={50} value={t.instant_paste_threshold}
            format={(v) => `${v} chars`} onChange={(v) => patch({ typing: { instant_paste_threshold: v } })} />
          <Slider label="Pre-type delay" min={0} max={500} step={10} value={t.pre_type_delay_ms}
            format={(v) => `${v} ms`} onChange={(v) => patch({ typing: { pre_type_delay_ms: v } })} />
        </div>
        <Toggle label="Restore clipboard after paste" description="Put your previous clipboard contents back"
          checked={t.restore_clipboard} onChange={(v) => patch({ typing: { restore_clipboard: v } })} />
      </Section>
    </div>
  );
}
