import { expect, test } from "vitest";
import { LOOKAHEAD_S, midiToY, NOW_X_FRACTION, pitchRange, timeToX, visibleSlice } from "./layout";

test("pitchRange pads and has a minimum span", () => {
  expect(pitchRange([{ start: 0, duration: 1, pitch: 60 }, { start: 1, duration: 1, pitch: 72 }])).toEqual({ min: 57, max: 75 });
  const r = pitchRange([{ start: 0, duration: 1, pitch: 60 }]);
  expect(r.max - r.min).toBe(12);
  expect((r.max + r.min) / 2).toBe(60);
  expect(pitchRange([])).toEqual({ min: 54, max: 66 });
});

test("midiToY puts high notes on top", () => {
  const r = { min: 50, max: 70 };
  expect(midiToY(70, r, 100, 500)).toBe(100);
  expect(midiToY(50, r, 100, 500)).toBe(500);
  expect(midiToY(60, r, 100, 500)).toBe(300);
});

test("timeToX anchors now and lookahead", () => {
  expect(NOW_X_FRACTION).toBe(0.3);
  expect(LOOKAHEAD_S).toBe(5);
  expect(timeToX(10, 10, 1000)).toBe(300);
  expect(timeToX(15, 10, 1000)).toBe(1000);
  expect(timeToX(7.5, 10, 1000)).toBeCloseTo(-50);
});

test("visibleSlice finds the notes inside a time window", () => {
  const notes = [0, 1, 2, 3, 4, 5].map((s) => ({ start: s, duration: 0.5, pitch: 60 }));
  expect(visibleSlice(notes, 1.2, 3.1)).toEqual([1, 4]);    // la nota che finisce a 1,5 è ancora visibile
  expect(visibleSlice(notes, 10, 20)).toEqual([6, 6]);
  expect(visibleSlice([], 0, 1)).toEqual([0, 0]);
});
