import { expect, test } from "vitest";
import { ScoreKeeper, starsFor } from "./scoring";

const sing = (k: ScoreKeeper, from: number, to: number, midi: number | null, step = 0.01) => {
  for (let t = from; t <= to + 1e-9; t += step) k.feed(t, midi);
};
const one = [{ start: 1, duration: 2, pitch: 60 }];

test("perfect note", () => {
  const k = new ScoreKeeper(one, "normal");
  sing(k, 0, 4, 60);
  k.finish();
  expect(k.result()).toEqual({ score: 200, accuracy: expect.closeTo(1, 2), stars: 5 });
});

test("an octave below counts", () => {
  const k = new ScoreKeeper(one, "hard");
  sing(k, 0, 4, 48);
  k.finish();
  expect(k.result().score).toBe(200);
});

test("tolerance depends on difficulty", () => {
  const e = new ScoreKeeper(one, "easy");
  const n = new ScoreKeeper(one, "normal");
  sing(e, 0, 4, 61.5);
  sing(n, 0, 4, 61.5);
  e.finish();
  n.finish();
  expect(e.result().score).toBe(200);
  expect(n.result().score).toBe(0);
});

test("singing outside notes costs nothing", () => {
  const k = new ScoreKeeper(one, "normal");
  sing(k, 0, 0.9, 72);
  sing(k, 1, 3, 60);
  sing(k, 3.1, 4, 40);
  k.finish();
  expect(k.result().score).toBe(200);
});

test("half a note", () => {
  const k = new ScoreKeeper(one, "normal");
  sing(k, 0, 2, 60);
  sing(k, 2.01, 4, null);
  k.finish();
  const r = k.result();
  expect(r.accuracy).toBeCloseTo(0.5, 1);
  expect(r.stars).toBe(2);
  expect(k.hitSegments(0)).toEqual([[expect.closeTo(1, 1), expect.closeTo(2, 1)]]);
});

test("separate hit stretches of the same note stay separate", () => {
  const k = new ScoreKeeper(one, "normal");
  sing(k, 0.9, 1.5, 60);
  sing(k, 1.51, 2.0, null);
  sing(k, 2.01, 3.5, 60);
  k.finish();
  expect(k.hitSegments(0)).toEqual([
    [expect.closeTo(1, 1), expect.closeTo(1.5, 1)],
    [expect.closeTo(2, 1), expect.closeTo(3, 1)],
  ]);
});

test("streak raises the multiplier and a miss resets it", () => {
  const notes = Array.from({ length: 7 }, (_, i) => ({ start: i, duration: 0.5, pitch: 60 }));
  const k = new ScoreKeeper(notes, "normal");
  sing(k, 0, 4.9, 60);
  expect(k.multiplier).toBe(2);        // 5 riuscite
  sing(k, 4.91, 5.9, null);
  expect(k.multiplier).toBe(1);        // la sesta mancata
  sing(k, 5.91, 7, 60);
  k.finish();
  expect(k.result().score).toBe(5 * 50 + 0 + 50);
});

test("gaps between readings are not credited", () => {                 // Review Focus 5
  const k = new ScoreKeeper(one, "normal");
  k.feed(1.0, 60);
  k.feed(3.0, 60);
  k.finish();
  expect(k.result().score).toBe(10);
});

test("readings that go back in time are ignored", () => {
  const k = new ScoreKeeper(one, "normal");
  sing(k, 0, 2, 60);
  k.feed(1.2, 60);
  sing(k, 2.01, 4, 60);
  k.finish();
  expect(k.result().score).toBe(200);
});

test("degenerate charts do not produce NaN", () => {                    // Review Focus 5
  for (const notes of [[], [{ start: 1, duration: 0, pitch: 60 }]]) {
    const k = new ScoreKeeper(notes, "normal");
    sing(k, 0, 3, 60);
    k.finish();
    expect(k.result()).toEqual({ score: 0, accuracy: 0, stars: 0 });
  }
});

test("finish closes the notes never reached", () => {
  const notes = Array.from({ length: 6 }, (_, i) => ({ start: i, duration: 0.5, pitch: 60 }));
  const k = new ScoreKeeper(notes, "normal");
  sing(k, 0, 4.9, 60);                 // 5 riuscite, la sesta mai raggiunta
  k.finish();
  expect(k.multiplier).toBe(1);
  expect(k.result().accuracy).toBeCloseTo(5 / 6, 2);
});

test("starsFor thresholds", () => {
  expect([0.95, 0.8, 0.6, 0.5, 0.3, 0.1].map(starsFor)).toEqual([5, 4, 3, 2, 1, 0]);
});

test("scoredUntil is the time of the last reading judged", () => {
  const k = new ScoreKeeper(one, "normal");
  expect(k.scoredUntil).toBe(-Infinity);
  k.feed(1.2, 60);
  k.feed(1.25, null);
  expect(k.scoredUntil).toBe(1.25);
});
