import { expect, test } from "vitest";
import { parseHash, toHash, type Route } from "./router";

test("router roundtrip", () => {
  const routes: Route[] = [
    { name: "library" },
    { name: "game", id: "yt-a_b-1" },
    { name: "verify", id: "file-12ab--mel" },
    { name: "edit", id: "yt-x" },
    { name: "result", id: "yt-x" },
    { name: "settings" },
    { name: "calibration" },
  ];
  for (const r of routes) expect(parseHash(toHash(r))).toEqual(r);
});

test("unknown or empty hashes fall back to the library", () => {
  expect(parseHash("")).toEqual({ name: "library" });
  expect(parseHash("#/boh/x")).toEqual({ name: "library" });
  expect(parseHash("#/game")).toEqual({ name: "library" });
});

test("ids with special characters survive the hash", () => {
  expect(parseHash(toHash({ name: "game", id: "file a/b" }))).toEqual({ name: "game", id: "file a/b" });
});
