/**
 * Unit tests for planBackendRestart. Plain node, no test framework:
 *   node electron/backend-supervisor.test.cjs
 * Exits non-zero if any assertion fails.
 */
"use strict";
const assert = require("assert");
const { planBackendRestart, MAX_BACKEND_RESTARTS } = require("./backend-supervisor.cjs");

let passed = 0;
function check(name, fn) {
  fn();
  passed++;
  console.log("ok -", name);
}

// A fresh crash with the port free retries with a 1s first backoff.
check("first crash retries after 1s", () => {
  const p = planBackendRestart({ quitting: false, exitCode: 1, ranMs: 2000, restarts: 0, portInUse: false });
  assert.strictEqual(p.action, "retry");
  assert.strictEqual(p.restarts, 1);
  assert.strictEqual(p.delayMs, 1000);
});

// Backoff doubles each consecutive failure.
check("backoff doubles: 1,2,4,8,16s", () => {
  const delays = [];
  let restarts = 0;
  for (let i = 0; i < 5; i++) {
    const p = planBackendRestart({ quitting: false, exitCode: 1, ranMs: 500, restarts, portInUse: false });
    delays.push(p.delayMs);
    restarts = p.restarts;
  }
  assert.deepStrictEqual(delays, [1000, 2000, 4000, 8000, 16000]);
});

// After the cap, give up instead of looping forever.
check("gives up after the cap", () => {
  const p = planBackendRestart({ quitting: false, exitCode: 1, ranMs: 500, restarts: MAX_BACKEND_RESTARTS, portInUse: false });
  assert.strictEqual(p.action, "giveup");
});

// The port being held (another instance / dev server) means adopt, never spawn —
// this is the fix for the every-few-seconds respawn loop.
check("adopts when the port is already in use", () => {
  const p = planBackendRestart({ quitting: false, exitCode: 1, ranMs: 500, restarts: 3, portInUse: true });
  assert.strictEqual(p.action, "adopt");
});

// Port-in-use adoption holds even at/above the cap (never a doomed spawn).
check("adopts even at the restart cap", () => {
  const p = planBackendRestart({ quitting: false, exitCode: 1, ranMs: 500, restarts: MAX_BACKEND_RESTARTS, portInUse: true });
  assert.strictEqual(p.action, "adopt");
});

// A backend that ran a good while before dying gets a fresh retry budget.
check("healthy run resets the restart counter", () => {
  const p = planBackendRestart({ quitting: false, exitCode: 1, ranMs: 60000, restarts: MAX_BACKEND_RESTARTS, portInUse: false });
  assert.strictEqual(p.action, "retry");
  assert.strictEqual(p.restarts, 1);   // reset to 0, then +1
  assert.strictEqual(p.delayMs, 1000);
});

// Intentional shutdown does nothing.
check("no action while quitting", () => {
  const p = planBackendRestart({ quitting: true, exitCode: null, ranMs: 5000, restarts: 2, portInUse: false });
  assert.strictEqual(p.action, "none");
});

// A clean exit (code 0) does nothing.
check("no action on clean exit", () => {
  const p = planBackendRestart({ quitting: false, exitCode: 0, ranMs: 5000, restarts: 0, portInUse: false });
  assert.strictEqual(p.action, "none");
});

// Backoff is clamped so it never grows unbounded.
check("backoff clamps at 30s", () => {
  const p = planBackendRestart({ quitting: false, exitCode: 1, ranMs: 500, restarts: 40, portInUse: false, max: 100 });
  assert.strictEqual(p.delayMs, 30000);
});

console.log(`\n${passed} passed`);
