/** Hotkey settings: current bindings, shortcut recorder, double-tap tuning. */
import { useState } from "react";
import { api } from "../lib/api";
import { useSettings } from "../hooks/useSettings";
import { Button, Kbd, PageHeader, Section, cn } from "../components/ui";

export default function HotkeysPage() {
  const { settings, patch } = useSettings();
  const [recording, setRecording] = useState<"ptt" | "toggle" | null>(null);

  if (!settings) return null;
  const hk = settings.hotkeys;

  const record = async (which: "ptt" | "toggle") => {
    setRecording(which);
    try {
      const r = await api.recordHotkey();
      if (r.combo) {
        if (which === "ptt") await patch({ hotkeys: { push_to_talk: r.combo } });
        else await patch({ hotkeys: { toggle_key: r.combo.split("+").pop() ?? r.combo } });
      }
    } finally {
      setRecording(null);
    }
  };

  const Binding = ({ label, description, value, which }: {
    label: string; description: string; value: string; which: "ptt" | "toggle";
  }) => (
    <div className="flex items-center justify-between py-3 border-b border-border/50 last:border-0">
      <div>
        <div className="text-sm font-medium">{label}</div>
        <div className="text-xs text-muted mt-0.5">{description}</div>
      </div>
      <div className="flex items-center gap-2">
        <span className={cn("rounded-lg border px-3 py-1.5 font-mono text-xs",
          recording === which ? "border-accent animate-pulse" : "border-border bg-elevated")}>
          {recording === which ? "Press keys…" : value}
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
      </Section>

      <Section title="Tips">
        <ul className="text-sm text-muted space-y-2">
          <li>• Hold <Kbd>{hk.push_to_talk}</Kbd> and speak — release to insert text.</li>
          <li>• While still holding <Kbd>{hk.push_to_talk}</Kbd>, tap <Kbd>{hk.clipboard_insert_key.toUpperCase()}</Kbd> mid-sentence
            to drop your <span className="text-fg">clipboard</span> into the dictation at that spot.</li>
          <li>• If a shortcut conflicts with another app, record a different combination above.</li>
        </ul>
      </Section>
    </div>
  );
}
