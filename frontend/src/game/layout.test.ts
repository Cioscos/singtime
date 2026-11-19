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

import { targetNote } from "./layout";

test("targetNote is the note being sung, or the nearest one in time", () => {
  const notes = [
    { start: 1, duration: 1, pitch: 60 },
    { start: 3, duration: 1, pitch: 64 },
    { start: 10, duration: 1, pitch: 67 },
  ];
  expect(targetNote(notes, 1.5)?.pitch).toBe(60);      // dentro la prima
  expect(targetNote(notes, 0.2)?.pitch).toBe(60);      // prima dell'inizio: la prima
  expect(targetNote(notes, 2.2)?.pitch).toBe(60);      // nella pausa, più vicina alla fine della prima
  expect(targetNote(notes, 2.8)?.pitch).toBe(64);      // nella pausa, più vicina all'inizio della seconda
  expect(targetNote(notes, 50)?.pitch).toBe(67);       // dopo la fine: l'ultima
  expect(targetNote([], 1)).toBeNull();
});

const bulk = () => Array.from({ length: 104 }, (_, i) => ({ start: i, duration: 0.5, pitch: 55 + (i % 13) }));   // da 55 a 67

test("pitchRange is not stretched by a stray note an octave off", () => {
  // un errore di ottava del rilevatore non deve schiacciare tutte le altre barre
  expect(pitchRange([...bulk(), { start: 200, duration: 0.2, pitch: 91 }])).toEqual({ min: 52, max: 70 });
  expect(pitchRange([{ start: -5, duration: 0.2, pitch: 31 }, ...bulk()])).toEqual({ min: 52, max: 70 });
});

test("pitchRange keeps a real high note close to the rest", () => {
  // l'acuto del ritornello, una volta sola e breve, fa parte del brano
  expect(pitchRange([...bulk(), { start: 200, duration: 0.2, pitch: 73 }])).toEqual({ min: 52, max: 76 });
});
