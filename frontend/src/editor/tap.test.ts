import { expect, test } from "vitest";
import type { LyricLine, Note } from "../lib/types";
import { tapBack, tapDown, tapFinish, tapStart, tapUp, type TapCursor, type TapOptions } from "./tap";

const line = (start: number, end: number, text: string, words: LyricLine["words"] = null): LyricLine => ({ start, end, text, words });
const note = (start: number, duration: number): Note => ({ start, duration, pitch: 60 });

const BY_LINE: TapOptions = { unit: "line", notes: [], snap: false };
const BY_WORD: TapOptions = { unit: "word", notes: [], snap: false };

/** Batte una sequenza di pressioni e rilasci: [giù, su] per ogni tocco. */
function play(lines: LyricLine[], from: number, taps: [number, number][], options: TapOptions) {
  let state = { lines, cursor: tapStart(from) };
  for (const [down, up] of taps) {
    state = tapDown(state.lines, state.cursor, down, options);
    state = tapUp(state.lines, state.cursor, up, options);
  }
  return state;
}

const spans = (lines: LyricLine[]) => lines.map((l) => [l.start, l.end]);

test("holding the key gives each line its start and its end", () => {
  const provisional = [line(0, 9, "a"), line(10, 19, "b"), line(20, 29, "c")];
  const { lines, cursor } = play(provisional, 0, [[30, 33], [34, 36.5]], BY_LINE);
  // La terza, non ancora battuta, è stata spinta avanti dal primo tocco e resta in coda.
  expect(spans(lines)).toEqual([[30, 33], [34, 36.5], [42, 51]]);
  expect(cursor).toMatchObject({ line: 2, downAt: null, pending: null });
});

test("lines waiting further ahead are left where they are", () => {
  const lines = [line(0, 2, "a"), line(40, 42, "b")];
  expect(spans(play(lines, 0, [[10, 12]], BY_LINE).lines)).toEqual([[10, 12], [40, 42]]);
});

test("a quick tap marks only the start: the end comes from the notes when the next line starts", () => {
  const notes = [note(30, 1), note(31.2, 1.5), note(34, 2)];
  const options: TapOptions = { unit: "line", notes, snap: false };
  const provisional = [line(0, 9, "a"), line(10, 19, "b")];
  let state = play(provisional, 0, [[30, 30.1]], options);
  expect(state.cursor.pending).toBe(0);
  state = tapDown(state.lines, state.cursor, 34, options);
  expect(state.lines[0]).toMatchObject({ start: 30, end: 32.7 });             // l'ultima nota prima della riga dopo
  expect(state.lines[1].start).toBe(34);
});

test("a quick tap on a line among good ones does not disturb the next", () => {
  const good = [line(10, 12, "a"), line(12.2, 14, "b")];
  const { lines } = play(good, 0, [[10.4, 10.5]], BY_LINE);
  expect(spans(lines)).toEqual([[10.4, 12.2], [12.2, 14]]);
});

test("stopping closes a line left pending", () => {
  const options: TapOptions = { unit: "line", notes: [note(30, 2)], snap: false };
  const state = play([line(0, 9, "a"), line(50, 52, "b")], 0, [[30, 30.1]], options);
  expect(tapFinish(state.lines, state.cursor, options)[0]).toMatchObject({ start: 30, end: 32 });
  expect(tapFinish(state.lines, tapStart(1), options)).toBe(state.lines);
});

test("starting a line while the previous one is still going cuts the previous one", () => {
  const lines = [line(10, 20, "a"), line(21, 22, "b")];
  const state = tapDown(lines, tapStart(1), 15, BY_LINE);
  expect(spans(state.lines)).toEqual([[10, 15], [15, 16]]);
});

test("taps snap to note attacks and releases to note ends", () => {
  const options: TapOptions = { unit: "line", notes: [note(30, 2.9)], snap: true };
  const { lines } = play([line(0, 1, "a")], 0, [[30.12, 33]], options);
  expect(lines[0]).toMatchObject({ start: 30, end: 32.9 });
  expect(play([line(0, 1, "a")], 0, [[30.4, 33.4]], options).lines[0]).toMatchObject({ start: 30.4, end: 33.4 });
});

test("a key that is already down, or a release without a press, changes nothing", () => {
  const lines = [line(0, 1, "a")];
  const down = tapDown(lines, tapStart(0), 5, BY_LINE);
  expect(tapDown(down.lines, down.cursor, 6, BY_LINE)).toEqual(down);
  expect(tapUp(lines, tapStart(0), 6, BY_LINE)).toEqual({ lines, cursor: tapStart(0) });
  expect(tapDown(lines, tapStart(1), 6, BY_LINE).lines).toBe(lines);         // oltre l'ultima riga
});

test("word by word: each tap starts a word, the hold ends it", () => {
  const { lines, cursor } = play([line(0, 6, "aa bb cc"), line(7, 8, "dopo")], 0, [[10, 10.5], [11, 11.4], [12, 13]], BY_WORD);
  expect(lines[0]).toEqual(line(10, 13, "aa bb cc", [
    { start: 10, end: 10.5, text: "aa" }, { start: 11, end: 11.4, text: "bb" }, { start: 12, end: 13, text: "cc" }]));
  expect(cursor).toMatchObject({ line: 1, word: 0, pending: null });
  expect(lines[1]).toMatchObject({ start: 13, end: 14 });                    // la riga dopo si accoda
});

test("word by word with quick taps: each word lasts until the next one", () => {
  const options: TapOptions = { unit: "word", notes: [note(12, 1.5)], snap: false };
  let state = play([line(0, 6, "aa bb cc"), line(40, 41, "dopo")], 0, [[10, 10.1], [11, 11.1], [12, 12.1]], options);
  expect(state.lines[0].words!.map((w) => [w.start, w.end]).slice(0, 2)).toEqual([[10, 11], [11, 12]]);
  expect(state.cursor).toMatchObject({ line: 1, word: 0, pending: 0 });
  state = tapDown(state.lines, state.cursor, 20, options);
  expect(state.lines[0].words![2]).toEqual({ start: 12, end: 13.5, text: "cc" });   // fino all'ultima nota
  expect(state.lines[0].end).toBe(13.5);
  expect(state.lines[1].start).toBe(20);
});

test("word by word keeps the words that are still to come after the one just tapped", () => {
  let state = tapDown([line(0, 6, "aa bb cc")], tapStart(0), 10, BY_WORD);
  state = tapUp(state.lines, state.cursor, 10.6, BY_WORD);
  const starts = state.lines[0].words!.map((w) => w.start);
  expect(starts[0]).toBe(10);
  expect(starts[1]).toBeGreaterThanOrEqual(10.6);
  expect(starts[2]).toBeGreaterThan(starts[1]);
  expect(state.cursor).toMatchObject({ line: 0, word: 1, wordPending: false });
});

test("a line without text is tapped as a whole even word by word", () => {
  const { lines, cursor } = play([line(0, 1, "  "), line(5, 6, "b")], 0, [[10, 12]], BY_WORD);
  expect(lines[0]).toMatchObject({ start: 10, end: 12, words: null });
  expect(cursor.line).toBe(1);
});

test("going back returns to the start of the line in progress, or to the previous line", () => {
  const cursor: TapCursor = { line: 3, word: 2, downAt: null, pending: null, wordPending: true };
  expect(tapBack(cursor)).toEqual(tapStart(3));
  expect(tapBack(tapStart(3))).toEqual(tapStart(2));
  expect(tapBack(tapStart(0))).toEqual(tapStart(0));
});
