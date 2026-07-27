/** Dictation settings: formatting, typing behavior, language, cleanup toggles. */
import { api, } from "../lib/api";
import { useEffect, useState } from "react";
import { useSettings } from "../hooks/useSettings";
import { PageHeader, Section, Select, Slider, Toggle } from "../components/ui";

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
