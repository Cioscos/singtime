import { expect, test } from "vitest";
import { detectOnsets, estimateLatencyMs, onsetCorrection } from "./latency";

const CLICKS = [1, 1.6, 2.2, 2.8, 3.4, 4.0, 4.6, 5.2];

test("estimateLatencyMs takes the median and tolerates a stray click", () => {
  const onsets = CLICKS.map((c, i) => c + (i === 3 ? 0.15 : 0.12));
  expect(estimateLatencyMs(CLICKS, onsets)).toBeCloseTo(120, 0);
});

test("estimateLatencyMs needs five clicks that agree", () => {
  expect(estimateLatencyMs(CLICKS, CLICKS.slice(0, 4).map((c) => c + 0.1))).toBeNull();
  expect(estimateLatencyMs([1, 1.6, 2.2], [1.1, 1.7, 2.3])).toBeNull();
  expect(estimateLatencyMs([], [])).toBeNull();
});

test("estimateLatencyMs refuses delays that do not agree with each other", () => {
  // rumori a caso (una cuffia che struscia, qualcuno che parla): ogni clic trova un "attacco", ma sparso
  const scattered = [0.05, 0.31, 0.12, 0.44, 0.2, 0.38, 0.09, 0.27];
  expect(estimateLatencyMs(CLICKS, CLICKS.map((c, i) => c + scattered[i]))).toBeNull();
});

test("estimateLatencyMs ignores sounds that are not answers to a click", () => {
  // un rumore prima del primo clic e uno fuori tempo non devono contare
  const onsets = [0.4, ...CLICKS.map((c) => c + 0.08), 2.75].sort((a, b) => a - b);
  expect(estimateLatencyMs(CLICKS, onsets)).toBeCloseTo(80, 0);
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

import { declaredLatencyMs } from "./latency";

test("declaredLatencyMs adds what output and input declare", () => {
  expect(declaredLatencyMs({ outputLatency: 0.04, baseLatency: 0.01 }, 0.02)).toBeCloseTo(60);
  expect(declaredLatencyMs({ outputLatency: 0, baseLatency: 0.01 }, undefined)).toBeCloseTo(10);   // uscita non dichiarata
  expect(declaredLatencyMs({}, NaN)).toBe(0);
  expect(declaredLatencyMs({ outputLatency: 5 }, 5)).toBe(500);                                    // valori assurdi: tetto
});
