/** Copy / favorite / delete controls for a single dictation, shared by the
 *  Home dashboard's recent activity and the full History page. */
import { useState } from "react";
import { Check, Copy, Star, Trash2 } from "lucide-react";
import { api, HistoryEntry } from "../lib/api";
import { cn } from "./ui";

export default function HistoryActions({ entry, onChange, size = 14, showCopy = true }: {
  entry: HistoryEntry;
  onChange: () => void;      // reload after favorite/delete mutates the store
  size?: number;
  showCopy?: boolean;        // Home hides this in favour of double-click-to-copy
}) {
  const [copied, setCopied] = useState(false);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(entry.final_text);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch { /* clipboard unavailable — silently ignore */ }
  };

  const btn = "p-1.5 rounded-lg hover:bg-elevated transition-colors";

  return (
    <div className="flex gap-1 shrink-0">
      {showCopy && (
        <button
          aria-label="Copy transcript"
          onClick={(e) => { e.stopPropagation(); copy(); }}
          className={cn(btn, "text-muted hover:text-fg")}>
          {copied ? <Check size={size} className="text-emerald-400" /> : <Copy size={size} />}
        </button>
      )}
      <button
        aria-label={entry.favorite ? "Remove favorite" : "Favorite"}
        onClick={(e) => { e.stopPropagation(); api.favorite(entry.id, !entry.favorite).then(onChange); }}
        className={cn(btn, entry.favorite ? "text-amber-400" : "text-muted hover:text-fg")}>
        <Star size={size} fill={entry.favorite ? "currentColor" : "none"} />
      </button>
      <button
        aria-label="Delete entry"
        onClick={(e) => { e.stopPropagation(); api.deleteHistory(entry.id).then(onChange); }}
        className={cn(btn, "text-muted hover:text-red-400")}>
        <Trash2 size={size} />
      </button>
    </div>
  );
}
