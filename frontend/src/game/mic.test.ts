import { afterEach, expect, test, vi } from "vitest";
import { Mic, MicDeniedError } from "./mic";

afterEach(() => vi.unstubAllGlobals());

function fakeStream() {
  const track = { stopped: false, label: "Finto", stop() { this.stopped = true; }, addEventListener() {} };
  return { track, stream: { getTracks: () => [track], getAudioTracks: () => [track] } };
}

test("the microphone is released when the setup fails after it was opened", async () => {
  const { track, stream } = fakeStream();
  vi.stubGlobal("navigator", { mediaDevices: { getUserMedia: async () => stream } });
  const ctx = { audioWorklet: { addModule: async () => { throw new Error("modulo non caricato"); } } };
  await expect(Mic.open(ctx as unknown as AudioContext)).rejects.toThrow("modulo non caricato");
  expect(track.stopped).toBe(true);        // niente spia di registrazione rimasta accesa
});

test("a refused permission becomes MicDeniedError", async () => {
  vi.stubGlobal("navigator", {
    mediaDevices: { getUserMedia: async () => { throw Object.assign(new Error("no"), { name: "NotAllowedError" }); } },
  });
  await expect(Mic.open({} as AudioContext)).rejects.toBeInstanceOf(MicDeniedError);
});
