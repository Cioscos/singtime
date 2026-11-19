import { expect, test } from "vitest";
import { SongPlayer, START_DELAY_S } from "./audio";

// Un AudioContext finto: registra quando e da dove parte ogni sorgente.
class FakeSource {
  buffer: unknown = null;
  onended: (() => void) | null = null;
  started: [number, number] | null = null;
  stopped = false;
  connect() { return this; }
  disconnect() {}
  start(when: number, offset: number) { this.started = [when, offset]; }
  stop() { this.stopped = true; }
}
class FakeGain {
  gain = { value: 1 };
  connect() { return this; }
  disconnect() {}
}
class FakeContext {
  currentTime = 0;
  outputLatency = 0.02;
  destination = {};
  sources: FakeSource[] = [];
  gains: FakeGain[] = [];
  createBufferSource() { const s = new FakeSource(); this.sources.push(s); return s; }
  createGain() { const g = new FakeGain(); this.gains.push(g); return g; }
}

function make(duration = 100) {
  const ctx = new FakeContext();
  const buffer = { duration } as AudioBuffer;
  const player = new SongPlayer(ctx as unknown as AudioContext, buffer, buffer);
  return { ctx, player };
}
const lastTwo = (ctx: FakeContext) => ctx.sources.slice(-2);

test("play starts both tracks at the same instant and position", () => {
  const { ctx, player } = make();
  ctx.currentTime = 5;
  player.play();
  expect(lastTwo(ctx).map((s) => s.started)).toEqual([[5 + START_DELAY_S, 0], [5 + START_DELAY_S, 0]]);
});

test("song time follows the audio clock", () => {
  const { ctx, player } = make();
  ctx.currentTime = 5;
  player.play();
  ctx.currentTime = 7.1;
  expect(player.songTime()).toBeCloseTo(2.0);
  expect(player.heardTime()).toBeCloseTo(1.98);        // quello che si sente è in ritardo dell'uscita audio
  expect(player.timeAt(6.1)).toBeCloseTo(1.0);
});

test("pause stops both tracks and resume continues from the same position", () => {
  const { ctx, player } = make();
  player.play();
  ctx.currentTime = 2.1;
  player.pause();
  expect(lastTwo(ctx).every((s) => s.stopped)).toBe(true);
  ctx.currentTime = 50;
  expect(player.songTime()).toBeCloseTo(2.0);
  player.play();
  expect(lastTwo(ctx).map((s) => s.started)).toEqual([[50.1, expect.closeTo(2.0)], [50.1, expect.closeTo(2.0)]]);
});

test("ten pause/resume cycles keep the two tracks aligned", () => {
  const { ctx, player } = make();
  let played = 0;
  for (let i = 0; i < 10; i++) {
    player.play();
    const [a, b] = lastTwo(ctx);
    expect(a.started).toEqual(b.started);
    expect(a.started![1]).toBeCloseTo(played);
    ctx.currentTime += START_DELAY_S + 1.37;             // suona per 1,37 s
    played += 1.37;
    player.pause();
    ctx.currentTime += 3;
  }
  expect(player.songTime()).toBeCloseTo(13.7);
});

test("seek moves both tracks, playing or paused", () => {
  const { ctx, player } = make();
  player.play();
  ctx.currentTime = 4;
  player.seek(60);
  expect(lastTwo(ctx).map((s) => s.started)).toEqual([[4.1, 60], [4.1, 60]]);
  player.pause();
  player.seek(10);
  expect(player.songTime()).toBe(10);
  expect(ctx.sources.length).toBe(4);                    // in pausa non parte nulla
});

test("pausing during the start delay does not go below zero", () => {
  const { ctx, player } = make();
  player.play();
  ctx.currentTime = 0.05;
  player.pause();
  expect(player.songTime()).toBe(0);
});

test("guide volume zero really silences the voice", () => {
  const { ctx, player } = make();
  player.setGuideVolume(0);
  const [instrumental, guide] = ctx.gains;
  expect(guide.gain.value).toBe(0);
  expect(instrumental.gain.value).toBe(1);
  player.setGuideVolume(3);
  expect(guide.gain.value).toBe(1);                      // limitato tra 0 e 1
});

test("onEnded fires once at the end of the song, not on pause", () => {
  const { ctx, player } = make(10);
  let ended = 0;
  player.onEnded = () => ended++;
  player.play();
  ctx.currentTime = 3;
  const paused = lastTwo(ctx);
  player.pause();
  paused.forEach((s) => s.onended?.());                  // lo stop manuale non è la fine del brano
  expect(ended).toBe(0);
  player.play();
  ctx.currentTime = 3 + START_DELAY_S + 7.2;
  lastTwo(ctx).forEach((s) => s.onended?.());
  expect(ended).toBe(1);
  expect(player.ended).toBe(true);
  player.play();                                         // a brano finito non riparte da solo
  expect(ctx.sources.length).toBe(4);
});
