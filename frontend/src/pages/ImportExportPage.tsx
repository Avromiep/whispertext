/** Import / Export: back up and restore the user's data in one file. Offers two
 *  categories — word data (vocabulary, text replacements, per-app rules) and app
 *  preferences (hotkeys, engine & model, audio, formatting toggles, theme) —
 *  that you tick per export/import. AI instructions, API keys and history are
 *  intentionally left out. */
import { useRef, useState } from "react";
import { Download, Upload } from "lucide-react";
import { API_BASE, bridge } from "../lib/api";
import {
  buildBackup, parseBackup, mergeVocabulary, mergeReplacements, mergePerTabRules,
  type BackupSelection,
} from "../lib/backup";
import { useSettings } from "../hooks/useSettings";
import { Button, PageHeader, Section, Toggle } from "../components/ui";

export default function ImportExportPage() {
  const { settings, patch } = useSettings();
  const [includeWords, setIncludeWords] = useState(true);
  const [includePrefs, setIncludePrefs] = useState(true);
  const [statusMsg, setStatusMsg] = useState("");
  const fileRef = useRef<HTMLInputElement>(null);

  const flash = (msg: string) => { setStatusMsg(msg); setTimeout(() => setStatusMsg(""), 6000); };

  if (!settings) return null;

  const nWords = settings.vocabulary.words.length;
  const nRepl = settings.formatting.text_replacements.length;
  const nRules = settings.formatting.per_tab_rules.length;
  const sel: BackupSelection = { wordData: includeWords, preferences: includePrefs };
  const nothingChosen = !includeWords && !includePrefs;

  const exportBackup = async () => {
    if (nothingChosen) return;
    if (bridge?.exportBackup) {
      const res = await bridge.exportBackup(buildBackup(settings, sel));
      flash(res?.ok ? `Exported to ${res.path}` : "Couldn't export the backup.");
    } else {
      window.open(`${API_BASE}/backup/export`);   // browser-dev fallback (both categories)
    }
  };

  const applyImportedText = async (text: string) => {
    const data = parseBackup(text);
    const patchObj: Record<string, unknown> = {};
    const applied: string[] = [];
    const skipped: string[] = [];

    const hasWords = data.vocabulary.length || data.text_replacements.length || data.per_tab_rules.length;
    if (hasWords) {
      if (includeWords) {
        const formatting: Record<string, unknown> = {
          text_replacements: mergeReplacements(settings.formatting.text_replacements, data.text_replacements),
          per_tab_rules: mergePerTabRules(settings.formatting.per_tab_rules, data.per_tab_rules),
        };
        patchObj.vocabulary = { words: mergeVocabulary(settings.vocabulary.words, data.vocabulary) };
        patchObj.formatting = formatting;
        if (data.vocabulary.length) applied.push(`${data.vocabulary.length} word${data.vocabulary.length === 1 ? "" : "s"}`);
        if (data.text_replacements.length) applied.push(`${data.text_replacements.length} replacement${data.text_replacements.length === 1 ? "" : "s"}`);
        if (data.per_tab_rules.length) applied.push(`${data.per_tab_rules.length} per-app rule${data.per_tab_rules.length === 1 ? "" : "s"}`);
      } else {
        skipped.push("word data");
      }
    }

    if (data.preferences) {
      if (includePrefs) {
        for (const [k, v] of Object.entries(data.preferences)) {
          if (k === "formatting") {
            patchObj.formatting = { ...(patchObj.formatting as object ?? {}), ...(v as object) };
          } else {
            patchObj[k] = v;
          }
        }
        applied.push("app preferences");
      } else {
        skipped.push("app preferences");
      }
    }

    if (Object.keys(patchObj).length === 0) {
      flash(skipped.length
        ? `That file has ${skipped.join(" and ")}, but those categories are turned off above.`
        : "No importable data found in that file.");
      return;
    }
    await patch(patchObj);
    flash(`Imported ${applied.join(", ")}.`
      + (skipped.length ? ` Skipped ${skipped.join(" and ")} (turned off above).` : ""));
  };

  const importBackup = async () => {
    if (bridge?.importBackup) {
      const res = await bridge.importBackup();
      if (res?.canceled) return;
      if (res?.ok && typeof res.text === "string") await applyImportedText(res.text);
      else flash("Couldn't read that file.");
    } else {
      fileRef.current?.click();
    }
  };

  const onImportFile = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (file) await applyImportedText(await file.text());
  };

  return (
    <div className="animate-fade-in">
      <PageHeader title="Import / Export"
        subtitle="Back up your data to a single file and restore it on another machine or after a reinstall. Choose what to include; the same choices apply when you import." />

      {statusMsg && (
        <div className="mb-4 text-xs text-muted bg-elevated border border-border rounded-xl px-3 py-2 animate-fade-in break-all">
          {statusMsg}
        </div>
      )}

      <Section title="What to include"
        description="These selections apply to both Export and Import. AI cleanup instructions, API keys, and history are never included.">
        <Toggle
          checked={includeWords}
          onChange={setIncludeWords}
          label="Word data"
          description={`Vocabulary, text replacements, and per-app rules — ${nWords} word${nWords === 1 ? "" : "s"}, ${nRepl} replacement${nRepl === 1 ? "" : "s"}, ${nRules} rule${nRules === 1 ? "" : "s"}.`}
        />
        <Toggle
          checked={includePrefs}
          onChange={setIncludePrefs}
          label="App preferences"
          description="Hotkeys & timing, chosen engine & model, audio, formatting toggles, and theme/font. Good for setting up a new PC."
        />
      </Section>

      <Section title="Back up or restore"
        description="Export writes one file to your Documents\WhisperText Backup folder. Import merges a backup into your current setup — your existing words and rules are kept, and anything matching is updated.">
        <div className="flex gap-2">
          <input ref={fileRef} type="file" accept=".json,.txt,application/json,text/plain"
            className="hidden" onChange={onImportFile} />
          <Button onClick={exportBackup} disabled={nothingChosen} variant="primary">
            <Download size={14} /> Export backup
          </Button>
          <Button onClick={importBackup}>
            <Upload size={14} /> Import backup
          </Button>
        </div>
        {nothingChosen && (
          <p className="text-xs text-muted mt-3">Turn on at least one category above to export.</p>
        )}
      </Section>
    </div>
  );
}
