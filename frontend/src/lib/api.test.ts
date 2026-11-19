import { afterEach, expect, test, vi } from "vitest";
import { addUrl, audioUrl, deleteSong, listSongs, patchSong } from "./api";

afterEach(() => vi.unstubAllGlobals());

test("api errors carry the server message", async () => {
  vi.stubGlobal("fetch", async () => new Response(JSON.stringify({ detail: "Video non disponibile" }), { status: 400 }));
  await expect(addUrl("x")).rejects.toThrow("Video non disponibile");
});

test("api errors without a body still say something", async () => {
  vi.stubGlobal("fetch", async () => new Response("", { status: 500 }));
  await expect(listSongs()).rejects.toThrow("Errore 500");
});

test("a server that is down gives a readable message", async () => {
  vi.stubGlobal("fetch", async () => { throw new TypeError("fetch failed"); });
  await expect(listSongs()).rejects.toThrow("Server non raggiungibile");
});

test("audioUrl encodes the id", () => {
  expect(audioUrl("file-1--a b", "vocals")).toBe("/api/songs/file-1--a%20b/audio/vocals");
});

test("requests go to the right place with a JSON body", async () => {
  const calls: [string, RequestInit | undefined][] = [];
  vi.stubGlobal("fetch", async (url: string, init?: RequestInit) => {
    calls.push([url, init]);
    return new Response(init?.method === "DELETE" ? null : "{}", { status: init?.method === "DELETE" ? 204 : 200 });
  });
  await patchSong("yt-a", { title: "Nuovo" });
  await deleteSong("yt-a");
  expect(calls[0][0]).toBe("/api/songs/yt-a");
  expect(calls[0][1]?.method).toBe("PATCH");
  expect(JSON.parse(calls[0][1]?.body as string)).toEqual({ title: "Nuovo" });
  expect(calls[1][1]?.method).toBe("DELETE");
});
