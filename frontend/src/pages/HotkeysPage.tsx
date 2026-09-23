/** Hotkey settings: current bindings, shortcut recorder, double-tap tuning. */
import { useState } from "react";
import { api } from "../lib/api";
import { useSettings } from "../hooks/useSettings";
import { Button, Kbd, PageHeader, Section, Slider, cn } from "../components/ui";

export default function HotkeysPage() {
  const { settings, patch } = useSettings();
  const [recording, setRecording] = useState<"ptt" | "toggle" | "insert" | null>(null);

  if (!settings) return null;
  const hk = settings.hotkeys;

  const record = async (which: "ptt" | "toggle" | "insert") => {
    setRecording(which);
    try {
      const r = await api.recordHotkey();
      if (r.combo) {
        // The insert key is a single key tapped while already holding push-to-talk,
        // so keep only the final (non-modifier) key of whatever was pressed.
        const lastKey = r.combo.split("+").pop() ?? r.combo;
        if (which === "ptt") await patch({ hotkeys: { push_to_talk: r.combo } });
        else if (which === "toggle") await patch({ hotkeys: { toggle_key: lastKey } });
        else await patch({ hotkeys: { clipboard_insert_key: lastKey } });
      }
    } finally {
      setRecording(null);
    }
  };

  const Binding = ({ label, description, value, which }: {
    label: string; description: string; value: string; which: "ptt" | "toggle" | "insert";
  }) => (
    <div className="flex items-center justify-between py-3 border-b border-border/50 last:border-0">
      <div>
        <div className="text-sm font-medium">{label}</div>
        <div className="text-xs text-muted mt-0.5">{description}</div>
      </div>
      <div className="flex items-center gap-2">
        <span className={cn("rounded-lg border px-3 py-1.5 font-mono text-xs",
          recording === which ? "border-accent animate-pulse" : "border-border bg-elevated")}>
          {recording === which ? (which === "insert" ? "Press a key…" : "Press keys…") : value}
        </span>
        <Button size="sm" onClick={() => record(which)} disabled={recording !== null}>
          Record
        </Button>
      </div>
    </div>
  );

  return (
    <div className="animate-fade-in">
      <PageHeader title="Hotkeys" subtitle="Global shortcuts — they work in every application." />

      <Section title="Bindings">
        <Binding label="Push-to-talk" description="Hold to record, release to type" value={hk.push_to_talk} which="ptt" />
        <Binding label="Clipboard-insert key"
          description={`Tap while holding push-to-talk to drop your clipboard in mid-sentence (so ${hk.push_to_talk} + this key)`}
          value={hk.clipboard_insert_key.toUpperCase()} which="insert" />
      </Section>

      <Section title="Release timing"
        description="After you let go, WhisperText waits this long and re-checks before finishing — so a grip-relax or key hiccup during a thinking pause doesn't cut you off. Higher = more forgiving of pauses; lower = snappier, especially on short one-word dictations.">
        <Slider label="Wait after release" min={100} max={1000} step={50}
          value={hk.release_grace_ms}
          format={(v) => `${(v / 1000).toFixed(2)} s`}
          onChange={(v) => patch({ hotkeys: { release_grace_ms: v } })} />
      </Section>

      <Section title="Tips">
        <ul className="text-sm text-muted space-y-2">
          <li>• Hold <Kbd>{hk.push_to_talk}</Kbd> and speak — release to insert text.</li>
          <li>• While still holding <Kbd>{hk.push_to_talk}</Kbd>, tap <Kbd>{hk.clipboard_insert_key.toUpperCase()}</Kbd> mid-sentence
            to drop your <span className="text-fg">clipboard</span> into the dictation at that spot.</li>
          <li>• If either binding above clashes with another app, Record a new one — pick a letter for the
            clipboard‑insert key that isn't already a <Kbd>{hk.push_to_talk}</Kbd> shortcut somewhere else.</li>
        </ul>
      </Section>
    </div>
  );
}
