import { expect, test } from "vitest";
import { noteName } from "./pitch-math";
import { HOP_SIZE, PitchWindow, WINDOW_SIZE } from "./pitch-window";

const ramp = (from: number, length: number) => Float32Array.from({ length }, (_, i) => from + i);

function collect(window: PitchWindow, blocks: Float32Array[]) {
  const out: { first: number; last: number; end: number; rms: number }[] = [];
  let frame = 0;
  for (const block of blocks) {
    window.push(block, frame, (samples, endFrame, rms) =>
      out.push({ first: samples[0], last: samples[samples.length - 1], end: endFrame, rms }));
    frame += block.length;
  }
  return out;
}

test("sizes match the plan", () => {
  expect([WINDOW_SIZE, HOP_SIZE]).toEqual([2048, 512]);
});

test("nothing is emitted until a full window has arrived", () => {
  const w = new PitchWindow(8, 4);
  expect(collect(w, [ramp(0, 4), ramp(4, 3)])).toEqual([]);
});

test("a window is emitted every hop, with the latest samples in order", () => {
  const w = new PitchWindow(8, 4);
  const blocks = [0, 1, 2, 3, 4, 5].map((i) => ramp(i * 3, 3));   // 18 campioni a blocchi da 3
  const out = collect(w, blocks);
  expect(out.map((o) => [o.first, o.last, o.end])).toEqual([[0, 7, 8], [4, 11, 12], [8, 15, 16]]);
});

test("render quanta of 128 samples give a reading every 512", () => {
  const w = new PitchWindow();
  const blocks = Array.from({ length: 40 }, (_, i) => ramp(i * 128, 128));
  const out = collect(w, blocks);
  expect(out.map((o) => o.end)).toEqual([2048, 2560, 3072, 3584, 4096, 4608, 5120]);
  expect(out[1].first).toBe(512);
});

test("rms measures the loudness of the window", () => {
  const w = new PitchWindow(4, 4);
  const out = collect(w, [Float32Array.from([0.5, -0.5, 0.5, -0.5]), Float32Array.from([0, 0, 0, 0])]);
  expect(out.map((o) => o.rms)).toEqual([0.5, 0]);
});

test("the emitted buffer is reused but always holds the current window", () => {
  const w = new PitchWindow(4, 2);
  const seen: number[][] = [];
  w.push(ramp(0, 8), 0, (samples) => seen.push(Array.from(samples)));
  expect(seen).toEqual([[0, 1, 2, 3], [2, 3, 4, 5], [4, 5, 6, 7]]);
});

test("noteName uses Italian names", () => {
  expect(noteName(69)).toBe("La4");
  expect(noteName(60)).toBe("Do4");
  expect(noteName(61.2)).toBe("Do♯4");
  expect(noteName(59.6)).toBe("Do4");
  expect(noteName(47)).toBe("Si2");
});
