import { expect, test } from "vitest";
import { lineAt, sungFraction } from "./lyrics-progress";

const lines = [
  { start: 10, end: 13, text: "uno due", words: null },
  { start: 14, end: 16, text: "tre", words: null },
  { start: 60, end: 62, text: "dopo", words: null },
];

test("lineAt shows a line slightly early and hides it in long breaks", () => {
  expect(lineAt(lines, 5)).toEqual({ current: -1, next: 0 });
  expect(lineAt(lines, 9.2)).toEqual({ current: 0, next: 1 });
  expect(lineAt(lines, 14.5)).toEqual({ current: 1, next: 2 });
  expect(lineAt(lines, 30)).toEqual({ current: -1, next: 2 });
  expect(lineAt(lines, 100)).toEqual({ current: -1, next: -1 });
  expect(lineAt([], 1)).toEqual({ current: -1, next: -1 });
});

test("sungFraction is uniform without word times", () => {
  expect(sungFraction(lines[0], 9)).toBe(0);
  expect(sungFraction(lines[0], 11.5)).toBeCloseTo(0.5);
  expect(sungFraction(lines[0], 20)).toBe(1);
});

test("sungFraction follows word times when present", () => {
  const l = { start: 0, end: 4, text: "aa bbbb", words: [{ start: 0, end: 1, text: "aa" }, { start: 3, end: 4, text: "bbbb" }] };
  expect(sungFraction(l, 2)).toBeCloseTo(2 / 6);
  expect(sungFraction(l, 3.5)).toBeCloseTo(4 / 6);
});

test("sungFraction survives a zero-length line", () => {
  expect(sungFraction({ start: 5, end: 5, text: "x", words: null }, 5)).toBe(1);
  expect(sungFraction({ start: 5, end: 5, text: "x", words: null }, 4)).toBe(0);
});

import { wordSpan } from "./lyrics-progress";

test("wordSpan follows word times", () => {
  const l = {
    start: 0, end: 4, text: "aa bbbb cc",
    words: [{ start: 0.2, end: 1, text: "aa" }, { start: 1.5, end: 3, text: "bbbb" }, { start: 3, end: 4, text: "cc" }],
  };
  expect(wordSpan(l, 0.1)).toEqual([0, 0]);        // non ancora cominciata
  expect(wordSpan(l, 0.5)).toEqual([0, 2]);
  expect(wordSpan(l, 1.2)).toEqual([3, 3]);        // tra due parole: nessuna in corso, la prima è cantata
  expect(wordSpan(l, 2)).toEqual([3, 7]);
  expect(wordSpan(l, 3.5)).toEqual([8, 10]);
  expect(wordSpan(l, 9)).toEqual([10, 10]);        // tutta cantata
});

test("wordSpan estimates the word when only the line is timed", () => {
  const l = { start: 10, end: 14, text: "uno due tre", words: null };     // 11 caratteri in 4 secondi
  expect(wordSpan(l, 9)).toEqual([0, 0]);
  expect(wordSpan(l, 10.5)).toEqual([0, 3]);
  expect(wordSpan(l, 12)).toEqual([4, 7]);
  expect(wordSpan(l, 13.9)).toEqual([8, 11]);
  expect(wordSpan(l, 14)).toEqual([11, 11]);
});

test("wordSpan gives up when words and text disagree", () => {
  const l = { start: 0, end: 2, text: "testo corretto", words: [{ start: 0, end: 1, text: "altro" }] };
  expect(wordSpan(l, 0.5)).toBeNull();
});
