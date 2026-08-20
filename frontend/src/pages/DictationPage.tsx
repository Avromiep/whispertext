/** Dictation settings: formatting, typing behavior, language, cleanup toggles. */
import { api, } from "../lib/api";
import { useEffect, useState } from "react";
import { useSettings } from "../hooks/useSettings";
import { PageHeader, Section, Select, Slider, Toggle } from "../components/ui";

/** One tab-title phrase per line. Local state so typing (incl. blank lines)
 * isn't disrupted; the stored setting is the trimmed, non-empty lines. */
function TitleList({ value, onChange }: { value: string[]; onChange: (v: string[]) => void }) {
  const [text, setText] = useState(value.join("\n"));
  return (
    <textarea
      value={text}
      onChange={(e) => {
        setText(e.target.value);
        onChange(e.target.value.split("\n").map((s) => s.trim()).filter(Boolean));
      }}
      rows={3}
      placeholder={"Gmail\nNotion\nMy Journal"}
      className="w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm font-mono resize-y focus:border-accent outline-none"
    />
  );
}

export default function DictationPage() {
  const { settings, patch } = useSettings();
  const [languages, setLanguages] = useState<Record<string, string>>({ auto: "Auto-detect" });

  useEffect(() => {
    api.systemInfo().then((i) => setLanguages(i.languages)).catch(() => {});
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

      <Section title="Per-tab layout" description="Format differently depending on which browser tab you're dictating into — matched by the tab's title, since the app can't read the tab's URL.">
        <div className="text-sm font-medium">One sentence per line</div>
        <p className="text-[11px] text-muted mt-0.5 mb-2">
          When the active tab's title contains one of these (one per line), each sentence is put on its
          own line with a blank line between. Use a word from the tab's title — the site or page name,
          e.g. "Gmail", "Notion", or a document's name.
        </p>
        <TitleList value={f.sentence_per_line_titles}
          onChange={(v) => patch({ formatting: { sentence_per_line_titles: v } })} />
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
