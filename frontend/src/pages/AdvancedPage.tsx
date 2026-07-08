/** Advanced: appearance, startup, debug, telemetry, whisper tuning, logs. */
import { FileDown } from "lucide-react";
import { api, API_BASE, bridge } from "../lib/api";
import { useEffect, useState } from "react";
import { useSettings } from "../hooks/useSettings";
import { Button, PageHeader, Section, Select, Slider, Toggle } from "../components/ui";

export default function AdvancedPage() {
  const { settings, patch } = useSettings();
  const [loginItem, setLoginItem] = useState(false);

  useEffect(() => { bridge?.getLoginItem().then(setLoginItem); }, []);

  if (!settings) return null;
  const g = settings.general;

  const setBoot = async (v: boolean) => {
    await patch({ general: { launch_on_boot: v } });
    if (bridge) setLoginItem(await bridge.setLoginItem(v));
    else setLoginItem(v);
  };

  return (
    <div className="animate-fade-in">
      <PageHeader title="Advanced" subtitle="Appearance, startup, and developer options." />

      <Section title="Appearance">
        <Select label="Theme" value={g.theme} onChange={(v) => patch({ general: { theme: v as never } })}
          options={[
            { value: "dark", label: "Dark (default)" },
            { value: "light", label: "Light" },
            { value: "system", label: "Follow system" },
          ]} />
        <div className="mt-3">
          <Slider label="Font scale" min={0.85} max={1.3} step={0.05} value={g.font_scale}
            format={(v) => `${Math.round(v * 100)}%`} onChange={(v) => patch({ general: { font_scale: v } })} />
        </div>
      </Section>

      <Section title="Startup & updates">
        <Toggle label="Launch on boot" description="Start WhisperText when you sign in"
          checked={g.launch_on_boot && loginItem} onChange={setBoot} />
        <Toggle label="Automatic updates" description="Download updates in the background"
          checked={g.auto_update} onChange={(v) => patch({ general: { auto_update: v } })} />
        <Toggle label="Desktop notifications" description="Dictation complete, model downloads, errors"
          checked={g.notifications} onChange={(v) => patch({ general: { notifications: v } })} />
      </Section>

      <Section title="Speech engine tuning">
        <Select label="Compute device" value={settings.whisper.compute_device}
          onChange={(v) => patch({ whisper: { compute_device: v } })}
          options={[
            { value: "auto", label: "Auto — GPU when available, CPU fallback" },
            { value: "cuda", label: "Force CUDA GPU" },
            { value: "cpu", label: "Force CPU (int8)" },
          ]} />
        <div className="mt-3">
          <Slider label="Beam size (accuracy vs speed)" min={1} max={10} step={1} value={settings.whisper.beam_size}
            onChange={(v) => patch({ whisper: { beam_size: v } })} />
        </div>
      </Section>

      <Section title="History retention">
        <Slider label="Auto-delete after" min={0} max={365} step={5} value={settings.history.retention_days}
          format={(v) => (v === 0 ? "Never" : `${v} days`)}
          onChange={(v) => patch({ history: { retention_days: v } })} />
      </Section>

      <Section title="Developer">
        <Toggle label="Debug mode" description="Verbose logging for troubleshooting"
          checked={g.debug_mode} onChange={(v) => patch({ general: { debug_mode: v } })} />
        <Toggle label="Telemetry" description="Anonymous usage statistics (off by default)"
          checked={g.telemetry} onChange={(v) => patch({ general: { telemetry: v } })} />
        <div className="flex gap-2 mt-3">
          <Button size="sm" onClick={() => bridge ? bridge.openExternal(`${API_BASE}/logs/export`) : window.open(`${API_BASE}/logs/export`)}>
            <FileDown size={13} /> Export logs
          </Button>
          <Button size="sm" onClick={() => api.pauseHotkeys(false)}>Restart hotkey service</Button>
        </div>
      </Section>
    </div>
  );
}
