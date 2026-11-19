import { expect, test } from "vitest";
import { SongClock } from "./song-clock";

test("clock starts, pauses and resumes", () => {
  const c = new SongClock();
  expect(c.now(5)).toBe(0);
  c.start(10);
  expect(c.running).toBe(true);
  expect(c.now(12.5)).toBe(2.5);
  c.pause(13);
  expect(c.running).toBe(false);
  expect(c.now(99)).toBe(3);
  c.start(100, c.now(100));
  expect(c.now(101)).toBe(4);
});

test("clock can start in the future and from an offset", () => {
  const c = new SongClock();
  c.start(10.1, 60);                 // parte tra un decimo di secondo, dal minuto 1
  expect(c.now(10)).toBeCloseTo(59.9);
  expect(c.now(11.1)).toBeCloseTo(61);
});
