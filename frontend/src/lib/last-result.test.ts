import { expect, test } from "vitest";
import { isNewRecord, saveLastResult, takeLastResult, type LastResult } from "./last-result";

function memoryStorage() {
  const data = new Map<string, string>();
  return {
    getItem: (key: string) => data.get(key) ?? null,
    setItem: (key: string, value: string) => void data.set(key, value),
    removeItem: (key: string) => void data.delete(key),
  };
}
const result: LastResult = { songId: "yt-a", difficulty: "normal", score: 1200, accuracy: 0.8, stars: 4 };

test("a result is handed over exactly once", () => {
  const storage = memoryStorage();
  saveLastResult(storage, result);
  expect(takeLastResult(storage, "yt-a")).toEqual(result);
  expect(takeLastResult(storage, "yt-a")).toBeNull();        // ricaricando la pagina non si reinvia
});

test("a result of another song is not taken", () => {
  const storage = memoryStorage();
  saveLastResult(storage, result);
  expect(takeLastResult(storage, "yt-b")).toBeNull();
  expect(takeLastResult(storage, "yt-a")).toEqual(result);
});

test("garbage in the storage is ignored and cleaned", () => {
  const storage = memoryStorage();
  storage.setItem("lastResult", "{non è json");
  expect(takeLastResult(storage, "yt-a")).toBeNull();
  storage.setItem("lastResult", JSON.stringify({ songId: "yt-a", score: "tanto" }));
  expect(takeLastResult(storage, "yt-a")).toBeNull();
  expect(storage.getItem("lastResult")).toBeNull();
});

test("isNewRecord compares with the previous best", () => {
  expect(isNewRecord(1200, undefined)).toBe(true);
  expect(isNewRecord(1200, { score: 1000, accuracy: 0.5, stars: 2, date: "" })).toBe(true);
  expect(isNewRecord(1000, { score: 1000, accuracy: 0.5, stars: 2, date: "" })).toBe(false);
  expect(isNewRecord(0, undefined)).toBe(false);             // zero punti non è un record
});
