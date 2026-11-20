import { expect, test } from "vitest";
import { History } from "./history";

test("undo and redo walk back and forth", () => {
  const history = new History<string>();
  expect(history.canUndo).toBe(false);
  expect(history.undo("a")).toBeUndefined();
  history.record("a");
  history.record("b");
  expect(history.undo("c")).toBe("b");
  expect(history.undo("b")).toBe("a");
  expect(history.canUndo).toBe(false);
  expect(history.redo("a")).toBe("b");
  expect(history.redo("b")).toBe("c");
  expect(history.canRedo).toBe(false);
});

test("a new change forgets what had been undone", () => {
  const history = new History<string>();
  history.record("a");
  history.undo("b");
  history.record("a");
  expect(history.canRedo).toBe(false);
});

test("changes with the same key are undone together", () => {
  const history = new History<string>();
  history.record("", "text:0");
  history.record("c", "text:0");
  history.record("ci", "text:0");
  history.record("cia", "text:1");          // un'altra riga: un altro passo
  expect(history.undo("ciao")).toBe("cia");
  expect(history.undo("cia")).toBe("");
  history.record("", "text:0");             // dopo un annulla si ricomincia a contare
  history.record("x", "text:0");
  expect(history.undo("xy")).toBe("");
  expect(history.canUndo).toBe(false);
});

test("the oldest states are dropped past the limit", () => {
  const history = new History<number>(2);
  [1, 2, 3].forEach((n) => history.record(n));
  expect(history.undo(4)).toBe(3);
  expect(history.undo(3)).toBe(2);
  expect(history.canUndo).toBe(false);
});
