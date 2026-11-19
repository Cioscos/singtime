import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { debounced } from "./debounce";

beforeEach(() => vi.useFakeTimers());
afterEach(() => vi.useRealTimers());

test("several quick calls become one, after the delay", () => {
  const run = vi.fn();
  const save = debounced(run, 300);
  save.schedule();
  vi.advanceTimersByTime(200);
  save.schedule();
  vi.advanceTimersByTime(299);
  expect(run).not.toHaveBeenCalled();
  expect(save.pending).toBe(true);
  vi.advanceTimersByTime(1);
  expect(run).toHaveBeenCalledTimes(1);
  expect(save.pending).toBe(false);
});

test("flush runs a waiting call at once, and only once", () => {
  // lasciando la schermata subito dopo una modifica, il salvataggio non deve perdersi
  const run = vi.fn();
  const save = debounced(run, 300);
  save.schedule();
  save.flush();
  expect(run).toHaveBeenCalledTimes(1);
  vi.advanceTimersByTime(1000);
  expect(run).toHaveBeenCalledTimes(1);
});

test("flush with nothing waiting does nothing", () => {
  const run = vi.fn();
  debounced(run, 300).flush();
  expect(run).not.toHaveBeenCalled();
});

test("cancel drops a waiting call", () => {
  const run = vi.fn();
  const save = debounced(run, 300);
  save.schedule();
  save.cancel();
  vi.advanceTimersByTime(1000);
  expect(run).not.toHaveBeenCalled();
});
