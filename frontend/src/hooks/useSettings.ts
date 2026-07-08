/** Settings context: loads once, deep-merges optimistic patches, persists via API. */
import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { api, Settings } from "../lib/api";

interface SettingsCtx {
  settings: Settings | null;
  patch: (p: DeepPartial<Settings>) => Promise<void>;
  reload: () => Promise<void>;
  backendUp: boolean;
}

export type DeepPartial<T> = { [K in keyof T]?: T[K] extends object ? DeepPartial<T[K]> : T[K] };

export const SettingsContext = createContext<SettingsCtx>({
  settings: null,
  patch: async () => {},
  reload: async () => {},
  backendUp: false,
});

export function useSettingsProvider(): SettingsCtx {
  const [settings, setSettings] = useState<Settings | null>(null);
  const [backendUp, setBackendUp] = useState(false);

  const reload = useCallback(async () => {
    try {
      setSettings(await api.getSettings());
      setBackendUp(true);
    } catch {
      setBackendUp(false);
    }
  }, []);

  useEffect(() => {
    reload();
    // Poll until the backend (spawned by Electron) comes up.
    const t = setInterval(() => {
      api.health().then(() => { setBackendUp(true); clearInterval(t); reload(); })
        .catch(() => setBackendUp(false));
    }, 1500);
    return () => clearInterval(t);
  }, [reload]);

  const patch = useCallback(async (p: DeepPartial<Settings>) => {
    const updated = await api.patchSettings(p);
    setSettings(updated);
  }, []);

  return { settings, patch, reload, backendUp };
}

export const useSettings = () => useContext(SettingsContext);
