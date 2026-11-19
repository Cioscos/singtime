import { expect, test } from "vitest";
import { detectOnsets, estimateLatencyMs, onsetCorrection } from "./latency";

test("estimateLatencyMs takes the median and ignores outliers", () => {
  const clicks = [1, 1.6, 2.2, 2.8, 3.4];
  expect(estimateLatencyMs(clicks, [1.12, 1.72, 2.32, 2.95, 3.52])).toBeCloseTo(120, 0);
});

test("estimateLatencyMs needs three matches", () => {
  expect(estimateLatencyMs([1, 1.6, 2.2], [1.1, 1.7])).toBeNull();
  expect(estimateLatencyMs([1, 1.6, 2.2], [1.9, 2.9, 3.9].map((x) => x + 5))).toBeNull();
  expect(estimateLatencyMs([], [])).toBeNull();
});

test("estimateLatencyMs ignores sounds that are not answers to a click", () => {
  const clicks = [1, 1.6, 2.2, 2.8];
  // un rumore prima del primo clic e uno a metà strada non devono contare
  expect(estimateLatencyMs(clicks, [0.4, 1.08, 1.68, 2.28, 2.75, 2.88])).toBeCloseTo(80, 0);
});

test("detectOnsets fires once per burst", () => {
  const r = Array.from({ length: 200 }, (_, i) => ({
    t: i * 0.01,
    rms: (i >= 50 && i < 55) || (i >= 120 && i < 130) ? 0.2 : 0.001,
  }));
  expect(detectOnsets(r, 0.05)).toEqual([expect.closeTo(0.5, 2), expect.closeTo(1.2, 2)]);
});

test("detectOnsets does not split a burst that flickers", () => {
  const loud = new Set([50, 51, 53, 54, 58]);          // buchi più corti di 0,15 s
  const r = Array.from({ length: 100 }, (_, i) => ({ t: i * 0.01, rms: loud.has(i) ? 0.2 : 0.001 }));
  expect(detectOnsets(r, 0.05)).toEqual([expect.closeTo(0.5, 2)]);
});

test("onsetCorrection accounts for the analysis window", () => {
  // un suono improvviso compare quando entra in coda alla finestra, il cui centro è più indietro
  expect(onsetCorrection(48000)).toBeCloseTo((2048 - 512) / 2 / 48000);
});
