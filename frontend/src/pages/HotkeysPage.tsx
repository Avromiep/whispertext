/** Hotkey settings: current bindings, shortcut recorder, double-tap tuning. */
import { useState } from "react";
import { api } from "../lib/api";
import { useSettings } from "../hooks/useSettings";
import { Button, Kbd, PageHeader, Section, Slider, Toggle, cn } from "../components/ui";

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
        <Toggle label="Hands-free toggle" description="Double-tap to start, double-tap again to stop — turn off to avoid accidental activation"
          checked={hk.hands_free_enabled} onChange={(v) => patch({ hotkeys: { hands_free_enabled: v } })} />
        {hk.hands_free_enabled && (
          <Binding label="Hands-free key" description="Which key to double-tap" value={`${hk.toggle_key} ×2`} which="toggle" />
        )}
      </Section>

      {hk.hands_free_enabled && (
        <Section title="Timing">
          <Slider label="Double-tap window" min={150} max={700} step={25} value={hk.double_tap_window_ms}
            format={(v) => `${v} ms`} onChange={(v) => patch({ hotkeys: { double_tap_window_ms: v } })} />
        </Section>
      )}

      <Section title="Tips">
        <ul className="text-sm text-muted space-y-2">
          <li>• Hold <Kbd>{hk.push_to_talk}</Kbd> and speak — release to insert text.</li>
          {hk.hands_free_enabled && (
            <li>• Double-tap <Kbd>{hk.toggle_key}</Kbd> for long dictations; double-tap again to finish.</li>
          )}
          <li>• <Kbd>Ctrl+K</Kbd> opens the command palette anywhere in this window.</li>
          <li>• If a shortcut conflicts with another app, record a different combination above.</li>
        </ul>
      </Section>
    </div>
  );
}
