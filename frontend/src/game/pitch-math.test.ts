import { expect, test } from "vitest";
import { foldToOctave, gate, hzToMidi } from "./pitch-math";

test("hzToMidi", () => {
  expect(hzToMidi(440)).toBeCloseTo(69);
  expect(hzToMidi(220)).toBeCloseTo(57);
});

test("foldToOctave picks the nearest octave", () => {
  expect(foldToOctave(48.2, 60)).toBeCloseTo(60.2);
  expect(foldToOctave(73, 60)).toBeCloseTo(61);
  expect(foldToOctave(65.9, 60)).toBeCloseTo(65.9);
  expect(foldToOctave(66.1, 60)).toBeCloseTo(54.1);
  expect(foldToOctave(24, 60)).toBeCloseTo(60);
});

test("gate rejects noise, silence and out-of-range", () => {
  expect(gate(220, 0.95, 0.05)).toBeCloseTo(57);
  expect(gate(220, 0.5, 0.05)).toBeNull();
  expect(gate(220, 0.95, 0.001)).toBeNull();
  expect(gate(30, 0.95, 0.05)).toBeNull();
  expect(gate(3000, 0.95, 0.05)).toBeNull();
  expect(gate(NaN, 0.95, 0.05)).toBeNull();
});
