/**
 * Pure decision logic for supervising the Python backend process, factored out
 * of main.cjs so it can be unit-tested without Electron.
 *
 * The backend owns a fixed port. When it exits we must decide whether to leave
 * it alone (something else now owns the port), restart it (a genuine crash),
 * or give up (it keeps failing to start) — with capped, backing-off retries so
 * a permanently-unstartable backend can't be respawned forever.
 */
"use strict";

const MAX_BACKEND_RESTARTS = 5;
const BACKEND_HEALTHY_MS = 30000;   // a run at least this long counts as healthy
const MAX_BACKOFF_MS = 30000;

/**
 * Decide what to do after the backend process exits.
 *
 * @param {object} s
 * @param {boolean} s.quitting     - the app is shutting down
 * @param {number|null} s.exitCode - child exit code (0 = clean)
 * @param {number} s.ranMs         - how long the process ran before exiting
 * @param {number} s.restarts      - consecutive failed restarts so far
 * @param {boolean} s.portInUse    - is something already listening on the port?
 * @param {number} [s.max]
 * @param {number} [s.healthyMs]
 * @returns {{action: "none"|"adopt"|"retry"|"giveup", restarts: number, delayMs?: number}}
 */
function planBackendRestart(s) {
  const max = s.max ?? MAX_BACKEND_RESTARTS;
  const healthyMs = s.healthyMs ?? BACKEND_HEALTHY_MS;

  // Intentional shutdown or a clean exit — nothing to do.
  if (s.quitting || s.exitCode === 0) return { action: "none", restarts: s.restarts };

  // A backend that stayed up a good while before dying earns a fresh budget.
  const restarts = s.ranMs >= healthyMs ? 0 : s.restarts;

  // Something already owns the port (a second instance, or a dev server) —
  // adopt it rather than spawning a competitor that can't bind.
  if (s.portInUse) return { action: "adopt", restarts };

  // It keeps failing to start — stop trying and let the UI surface it.
  if (restarts >= max) return { action: "giveup", restarts };

  const next = restarts + 1;
  const delayMs = Math.min(MAX_BACKOFF_MS, 1000 * 2 ** (next - 1)); // 1,2,4,8,16s
  return { action: "retry", restarts: next, delayMs };
}

module.exports = { planBackendRestart, MAX_BACKEND_RESTARTS, BACKEND_HEALTHY_MS };
