/** Dictation settings: formatting, typing behavior, language, cleanup toggles. */
import { api } from "../lib/api";
import type { PerTabRule } from "../lib/api";
import { useEffect, useState } from "react";
import { useSettings } from "../hooks/useSettings";
import { PageHeader, Section, Select, Slider, Toggle } from "../components/ui";

/** Per-site layout rules: a match phrase (page title or URL word) plus how to
 * space the sentences — a blank line between each, or none. */
function RulesList({ value, onChange }: { value: PerTabRule[]; onChange: (v: PerTabRule[]) => void }) {
  const setRule = (i: number, patch: Partial<PerTabRule>) =>
    onChange(value.map((r, j) => (j === i ? { ...r, ...patch } : r)));
  const remove = (i: number) => onChange(value.filter((_, j) => j !== i));
  const add = () => onChange([...value, { match: "", blank_line: true }]);

  return (
    <div className="space-y-2">
      {value.map((r, i) => (
        <div key={i} className="flex items-center gap-2">
          <input
            value={r.match}
            onChange={(e) => setRule(i, { match: e.target.value })}
            placeholder="Gmail, Notion, example.com…"
            className="flex-1 min-w-0 rounded-lg border border-border bg-surface px-3 py-2 text-sm font-mono focus:border-accent outline-none"
          />
          <div className="flex rounded-lg border border-border overflow-hidden text-xs shrink-0">
            <button type="button" onClick={() => setRule(i, { blank_line: true })}
              title="A blank line between each sentence"
              className={r.blank_line ? "bg-accent text-white px-2.5 py-2" : "text-muted hover:text-fg px-2.5 py-2"}>
              Blank line
            </button>
            <button type="button" onClick={() => setRule(i, { blank_line: false })}
              title="Each sentence on the next line, no gap"
              className={!r.blank_line ? "bg-accent text-white px-2.5 py-2" : "text-muted hover:text-fg px-2.5 py-2"}>
              No blank line
            </button>
          </div>
          <button type="button" onClick={() => remove(i)} aria-label="Remove"
            className="text-muted hover:text-red-400 px-1 py-2 shrink-0 text-sm">✕</button>
        </div>
      ))}
      <button type="button" onClick={add} className="text-xs text-accent hover:underline">
        + Add a site
      </button>
    </div>
  );
}

export default function DictationPage() {
  const { settings, patch } = useSettings();
  const [languages, setLanguages] = useState<Record<string, string>>({ auto: "Auto-detect" });
  // The window title captured for the most recent dictation — shown under the
  // per-tab list so you can see the EXACT text to match (the app only sees the
  // title bar, never the URL, so this is the string that matters).
  const [lastTitle, setLastTitle] = useState<string>("");

  useEffect(() => {
    api.systemInfo().then((i) => setLanguages(i.languages)).catch(() => {});
    api.history().then((h) => {
      const withTitle = h.find((e) => e.app && e.app.trim());
      if (withTitle) setLastTitle(withTitle.app);
    }).catch(() => {});
  }, []);

  if (!settings) return null;
  const f = settings.formatting;
  const t = settings.typing;

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
        <Toggle label="Numbers as digits" description={'Spoken numbers become digits: "three" → 3, "twenty three" → 23'}
          checked={f.numbers_as_digits} onChange={(v) => patch({ formatting: { numbers_as_digits: v } })} />
      </Section>

      <Section title="Per-tab layout" description="On matching sites, put each sentence on its own line — matched by the tab's page title or URL.">
        <p className="text-[11px] text-muted mb-2 leading-relaxed">
          Add a site by a word from its <span className="text-fg">page title</span> or{" "}
          <span className="text-fg">URL</span> — e.g. <span className="font-mono">Gmail</span>,{" "}
          <span className="font-mono">Notion</span>, or a domain like{" "}
          <span className="font-mono">example.com</span>. Then choose the spacing:{" "}
          <span className="text-fg">Blank line</span> puts an empty line between each sentence;{" "}
          <span className="text-fg">No blank line</span> stacks them on consecutive lines.
          Works in Chrome, Edge, and Arc.
        </p>
        <RulesList value={f.per_tab_rules}
          onChange={(v) => patch({ formatting: { per_tab_rules: v } })} />
        {lastTitle && (
          <p className="text-[11px] text-muted mt-2 leading-relaxed">
            Your most recent dictation was in a window titled:{" "}
            <span className="font-mono text-fg break-all">“{lastTitle}”</span>
            <br />In Chrome/Edge that includes the page name; Arc shows only “Arc”, so match the page
            title or a word from the URL (like the domain) instead.
          </p>
        )}
      </Section>

      <Section title="Typing" description="How the final text is inserted at your cursor.">
        <Select
          value={t.method}
          onChange={(v) => patch({ typing: { method: v } })}
          options={[
            { value: "auto", label: "Auto (recommended) — paste via clipboard" },
            { value: "keystrokes", label: "Always simulate keystrokes" },
            { value: "clipboard", label: "Always paste via clipboard" },
          ]}
          label="Insertion method"
        />
        <p className="text-[11px] text-muted mt-2">
          Paste inserts the whole text at once — fast and reliable everywhere. Choose keystrokes
          only for an app that ignores Ctrl+V (some terminals); it types character by character.
        </p>
        <div className="mt-4 space-y-3">
          <Slider label="Typing speed (keystrokes mode)" min={50} max={1000} step={25} value={t.chars_per_second}
            format={(v) => `${v} chars/s`} onChange={(v) => patch({ typing: { chars_per_second: v } })} />
          <Slider label="Pre-type delay" min={0} max={500} step={10} value={t.pre_type_delay_ms}
            format={(v) => `${v} ms`} onChange={(v) => patch({ typing: { pre_type_delay_ms: v } })} />
        </div>
        <Toggle label="Restore clipboard after paste" description="Put your previous clipboard contents back"
          checked={t.restore_clipboard} onChange={(v) => patch({ typing: { restore_clipboard: v } })} />
      </Section>
    </div>
  );
}
