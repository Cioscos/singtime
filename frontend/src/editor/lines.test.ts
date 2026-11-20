import { expect, test } from "vitest";
import type { LyricLine, Note } from "../lib/types";
import {
  addLineAfter, addLineAt, autoEnd, distribute, ensureWords, forSave, formatClock, lineIndexAt, lineIssue, markStart,
  mergeLines, moveLine, moveWordEdge, parseClock, removeLine, resizeEnd, resizeStart, setText, shiftAll, snapTime,
  splitLine, wordsOf,
} from "./lines";

const line = (start: number, end: number, text: string, words: LyricLine["words"] = null): LyricLine => ({ start, end, text, words });
const note = (start: number, duration: number): Note => ({ start, duration, pitch: 60 });

const three = (): LyricLine[] => [line(10, 12, "uno due"), line(13, 15, "tre"), line(20, 22, "quattro")];
const SONG = 60;

test("operations never touch the list they are given", () => {
  const lines = three();
  const copy = structuredClone(lines);
  moveLine(lines, 1, 14, SONG);
  resizeStart(lines, 1, 12.5, SONG);
  markStart(lines, 1, 11, SONG);
  splitLine(lines, 0, 3);
  mergeLines(lines, 0);
  addLineAfter(lines, 0, SONG);
  shiftAll(lines, 1);
  expect(lines).toEqual(copy);
});

const spans = (lines: LyricLine[]) => lines.map((l) => [l.start, l.end]);

test("a moved line keeps its length and shortens the neighbour it runs into", () => {
  const lines = three();                                                              // 10–12, 13–15, 20–22
  expect(moveLine(lines, 1, 16, SONG)).toEqual([lines[0], line(16, 18, "tre"), lines[2]]);   // nello spazio libero le vicine restano
  expect(spans(moveLine(lines, 1, 19, SONG))).toEqual([[10, 12], [19, 21], [21, 22]]);
  expect(spans(moveLine(lines, 1, 11, SONG))).toEqual([[10, 11], [11, 13], [20, 22]]);
  expect(spans(moveLine(lines, 1, 100, SONG))).toEqual([[10, 12], [19.9, 21.9], [21.9, 22]]);   // la vicina non sparisce
  expect(moveLine(lines, 1, 0, SONG)[1].start).toBe(10.1);
  expect(moveLine(lines, 2, 100, SONG)[2]).toMatchObject({ start: 58, end: 60 });    // l'ultima si ferma a fine brano
  expect(moveLine(lines, 1, 13, SONG)).toBe(lines);                                   // nessuno spostamento: stesso elenco
});

test("word times move with the line; stretching it touches only the word at the edge", () => {
  const lines = [line(10, 12, "uno due", [{ start: 10, end: 10.5, text: "uno" }, { start: 11, end: 12, text: "due" }])];
  expect(moveLine(lines, 0, 20, SONG)[0].words).toEqual([{ start: 20, end: 20.5, text: "uno" }, { start: 21, end: 22, text: "due" }]);
  expect(resizeEnd(lines, 0, 14, SONG)[0].words).toEqual([{ start: 10, end: 10.5, text: "uno" }, { start: 11, end: 14, text: "due" }]);
  expect(resizeEnd(lines, 0, 11.4, SONG)[0].words).toEqual([{ start: 10, end: 10.5, text: "uno" }, { start: 11, end: 11.4, text: "due" }]);
  expect(resizeStart(lines, 0, 9, SONG)[0].words![0]).toEqual({ start: 9, end: 10.5, text: "uno" });
  // Una parola rimasta fuori dalla riga si riduce a niente sul bordo, le altre non si muovono.
  expect(resizeStart(lines, 0, 10.8, SONG)[0].words).toEqual([{ start: 10.8, end: 10.8, text: "uno" }, { start: 11, end: 12, text: "due" }]);
  const detached = [line(10, 12, "uno", [{ start: 10.4, end: 11, text: "uno" }])];
  expect(resizeStart(detached, 0, 9, SONG)[0].words).toEqual([{ start: 10.4, end: 11, text: "uno" }]);   // non era attaccata al bordo
});

test("an edge pushed into the neighbour shortens it, down to a minimum", () => {
  const lines = three();
  expect(spans(resizeStart(lines, 1, 11, SONG))).toEqual([[10, 11], [11, 15], [20, 22]]);
  expect(resizeStart(lines, 1, 0, SONG)[1].start).toBe(10.1);
  expect(resizeStart(lines, 1, 99, SONG)[1].start).toBe(14.9);
  expect(spans(resizeEnd(lines, 1, 21, SONG))).toEqual([[10, 12], [13, 21], [21, 22]]);
  expect(resizeEnd(lines, 1, 99, SONG)[1].end).toBe(21.9);
  expect(resizeEnd(lines, 1, 0, SONG)[1].end).toBe(13.1);
  expect(resizeEnd(lines, 1, 17, SONG)[2]).toBe(lines[2]);                            // nello spazio libero la vicina non cambia
});

test("a shared boundary moves for both lines", () => {
  const lines = [line(10, 13, "a"), line(13, 15, "b")];
  expect(spans(resizeStart(lines, 1, 13.5, SONG, true))).toEqual([[10, 13.5], [13.5, 15]]);
  expect(spans(resizeStart(lines, 1, 13.5, SONG))).toEqual([[10, 13], [13.5, 15]]);   // da solo lascia uno spazio
  expect(spans(resizeEnd(lines, 0, 12, SONG, true))).toEqual([[10, 12], [12, 15]]);
  expect(spans(resizeEnd(lines, 0, 14, SONG, true))).toEqual([[10, 14], [14, 15]]);
});

test("lines that already overlap are not pushed apart by touching them", () => {
  const lines = [line(10, 14, "a"), line(13, 15, "b")];
  expect(spans(resizeEnd(lines, 1, 16, SONG))).toEqual([[10, 14], [13, 16]]);
  expect(spans(moveLine(lines, 1, 13.5, SONG))).toEqual([[10, 14], [13.5, 15.5]]);
});

test("marking the start inside the line moves only the start", () => {
  expect(markStart(three(), 1, 13.6, SONG)[1]).toMatchObject({ start: 13.6, end: 15 });
});

test("marking the start after the line moves the whole line, up to the next one", () => {
  expect(markStart(three(), 1, 17, SONG)[1]).toMatchObject({ start: 17, end: 19 });
  expect(markStart(three(), 1, 19, SONG)[1]).toMatchObject({ start: 19, end: 20 });
});

test("marking the start while the previous line is still going cuts the previous line", () => {
  const marked = markStart(three(), 1, 11.5, SONG);
  expect(marked[0]).toMatchObject({ start: 10, end: 11.5 });
  expect(marked[1]).toMatchObject({ start: 11.5, end: 15 });
  expect(markStart(three(), 1, 3, SONG)[1].start).toBe(10.1);              // mai prima dell'inizio della precedente
});

test("shifting everything keeps the shape and stops at zero", () => {
  const lines = [line(2, 3, "a", [{ start: 2, end: 3, text: "a" }]), line(5, 6, "b")];
  expect(shiftAll(lines, 0.5).map((l) => l.start)).toEqual([2.5, 5.5]);
  expect(shiftAll(lines, 0.5)[0].words![0]).toEqual({ start: 2.5, end: 3.5, text: "a" });
  expect(shiftAll(lines, -10).map((l) => [l.start, l.end])).toEqual([[0, 1], [3, 4]]);
  expect(shiftAll(lines, 0)).toBe(lines);
});

test("word times survive a spelling fix but not a different number of words", () => {
  const timed = line(1, 3, "ciao mondo", [{ start: 1, end: 2, text: "ciao" }, { start: 2, end: 3, text: "mondo" }]);
  const fixed = setText([timed], 0, "Ciao  Mondo!")[0];
  expect(wordsOf(fixed)).toEqual([{ start: 1, end: 2, text: "Ciao" }, { start: 2, end: 3, text: "Mondo!" }]);
  expect(wordsOf(setText([timed], 0, "ciao bel mondo")[0])).toBeNull();
  // Mentre si scrive il conto può non tornare: i tempi non si buttano, tornano buoni appena torna.
  expect(wordsOf(setText(setText([timed], 0, "ciao"), 0, "ciao mondi")[0])).toHaveLength(2);
});

test("estimated words share the line by length", () => {
  expect(ensureWords(line(10, 16, "aa bbbb"))).toEqual([{ start: 10, end: 12, text: "aa" }, { start: 12, end: 16, text: "bbbb" }]);
  expect(ensureWords(line(10, 16, "  "))).toEqual([]);
});

test("splitting between timed words uses their times", () => {
  const timed = line(1, 5, "uno due tre", [
    { start: 1, end: 1.5, text: "uno" }, { start: 2, end: 2.5, text: "due" }, { start: 4, end: 5, text: "tre" }]);
  const split = splitLine([timed], 0, 8)!;
  expect(split).toEqual([
    line(1, 2.5, "uno due", [{ start: 1, end: 1.5, text: "uno" }, { start: 2, end: 2.5, text: "due" }]),
    line(4, 5, "tre", [{ start: 4, end: 5, text: "tre" }]),
  ]);
});

test("splitting without word times shares the time by letters", () => {
  expect(splitLine([line(10, 16, "aa bbbb")], 0, 2)).toEqual([line(10, 12, "aa"), line(12, 16, "bbbb")]);
  expect(splitLine([line(10, 16, "aa bbbb")], 0, 0)).toBeNull();
  expect(splitLine([line(10, 16, "aa bbbb")], 0, 7)).toBeNull();
});

test("splitting inside a word drops the word times", () => {
  const timed = line(1, 3, "ciaomondo", [{ start: 1, end: 3, text: "ciaomondo" }]);
  expect(splitLine([timed], 0, 4)).toEqual([line(1, 1.889, "ciao"), line(1.889, 3, "mondo")]);
});

test("merging joins texts, times and word times", () => {
  const a = line(1, 2, "uno", [{ start: 1, end: 2, text: "uno" }]);
  const b = line(3, 4, "due", [{ start: 3, end: 4, text: "due" }]);
  expect(mergeLines([a, b, line(9, 10, "tre")], 0)).toEqual({
    lines: [line(1, 4, "uno due", [{ start: 1, end: 2, text: "uno" }, { start: 3, end: 4, text: "due" }]), line(9, 10, "tre")],
    caret: 4,
  });
  expect(mergeLines([a, line(3, 4, "due")], 0)!.lines[0].words).toBeNull();
  expect(mergeLines([a], 0)).toBeNull();
});

test("merging with an empty line just removes the empty one", () => {
  const full = line(1, 2, "uno");
  expect(mergeLines([full, line(2, 4, " ")], 0)).toEqual({ lines: [full], caret: 3 });
  expect(mergeLines([line(0, 1, ""), full], 0)).toEqual({ lines: [full], caret: 0 });
});

test("a new line goes in the free space after the chosen one", () => {
  const added = addLineAfter(three(), 1, SONG);
  expect(added.index).toBe(2);
  expect(added.lines[2]).toEqual(line(15, 17, ""));
  expect(addLineAfter(three(), 0, SONG).lines[1]).toEqual(line(12, 13, ""));          // c'è solo un secondo
  expect(addLineAfter(three(), 2, SONG).lines[3]).toEqual(line(22, 24, ""));
  expect(addLineAfter([], -1, SONG)).toEqual({ lines: [line(0, 2, "")], index: 0 });
});

test("without free space the neighbour gives up half of its time", () => {
  const tight = [line(0.1, 4, "a"), line(4, 8, "b")];
  expect(addLineAfter(tight, 0, SONG).lines).toEqual([line(0.1, 2.05, "a"), line(2.05, 4, ""), line(4, 8, "b")]);
  expect(addLineAfter(tight, -1, SONG).lines).toEqual([line(0.1, 2.05, ""), line(2.05, 4, "a"), line(4, 8, "b")]);
});

test("a line added at the playhead starts there when nobody is singing", () => {
  expect(addLineAt(three(), 16, SONG)).toEqual({ lines: [three()[0], three()[1], line(16, 18, ""), three()[2]], index: 2 });
  expect(addLineAt(three(), 2, SONG).index).toBe(0);
  expect(addLineAt(three(), 13.5, SONG).lines[2]).toEqual(line(15, 17, ""));          // dentro una riga: va dopo
  expect(addLineAt(three(), 19.9, SONG).lines[2]).toEqual(line(15, 17, ""));          // troppo a ridosso della successiva
});

test("removing a line leaves the others alone", () => {
  expect(removeLine(three(), 1).map((l) => l.text)).toEqual(["uno due", "quattro"]);
});

test("pasted text without times is spread where the singing is", () => {
  const spread = distribute(["a", "b"], [note(10, 1), note(29, 1)], 100);
  expect(spread).toEqual([line(10, 19, "a"), line(20, 29, "b")]);
  expect(distribute(["a", "b"], [], 100).map((l) => l.start)).toEqual([0, 50]);
  expect(distribute([], [], 100)).toEqual([]);
});

test("a line ends with the last note sung before the next line", () => {
  const notes = [note(10, 1), note(11.5, 2), note(20, 1)];
  expect(autoEnd(10.1, 20, notes)).toBe(13.5);          // la nota già cominciata conta
  expect(autoEnd(10, 12, notes)).toBe(12);              // mai oltre la riga successiva
  expect(autoEnd(14, 19, notes)).toBe(19);              // nessuno canta: fino alla successiva…
  expect(autoEnd(22, 90, notes)).toBe(28);              // …ma non per più di sei secondi
  expect(autoEnd(13.6, 90, notes)).toBe(19.6);          // un canto che arriva così tardi non è suo
  expect(autoEnd(10.1, 90, notes)).toBe(13.5);          // la frase finisce dove la voce tace a lungo
  expect(autoEnd(10.1, 90, [...notes.slice(0, 2), note(15, 1)])).toBe(16);   // una pausa breve sta dentro la riga
  expect(autoEnd(10, 10, notes)).toBe(10.1);
});

test("times snap to the nearest note edge within reach", () => {
  const notes = [note(10, 1), note(12, 2)];
  expect(snapTime(10.1, notes, "start", 0.15)).toBe(10);
  expect(snapTime(11.9, notes, "start", 0.15)).toBe(12);
  expect(snapTime(11, notes, "start", 0.15)).toBe(11);
  expect(snapTime(11.05, notes, "end", 0.15)).toBe(11);
  expect(snapTime(13.9, notes, "end", 0.15)).toBe(14);
});

test("a shared word boundary moves as one, a free edge alone", () => {
  const lines = [line(0, 4, "aa bb cc", [
    { start: 0, end: 1, text: "aa" }, { start: 1, end: 2, text: "bb" }, { start: 3, end: 4, text: "cc" }])];
  expect(moveWordEdge(lines, 0, 1, "start", 1.4, true)[0].words!.slice(0, 2)).toEqual([
    { start: 0, end: 1.4, text: "aa" }, { start: 1.4, end: 2, text: "bb" }]);
  expect(moveWordEdge(lines, 0, 1, "start", 0.5, false)[0].words![1].start).toBe(1);   // da sola non scavalca la precedente
  expect(moveWordEdge(lines, 0, 1, "end", 2.6, false)[0].words![1].end).toBe(2.6);
  expect(moveWordEdge(lines, 0, 1, "end", 9, false)[0].words![1].end).toBe(3);
  expect(moveWordEdge(lines, 0, 2, "end", 9, false)[0].words![2].end).toBe(4);         // l'ultima resta nella riga
  expect(moveWordEdge(lines, 0, 0, "start", -3, false)[0].words![0].start).toBe(0);
  expect(moveWordEdge([line(0, 4, "senza tempi")], 0, 0, "start", 1, false)[0].words).toBeNull();
});

test("the line being sung is found by time", () => {
  const lines = three();
  expect([9, 10, 11.9, 12, 14, 30].map((t) => lineIndexAt(lines, t))).toEqual([-1, 0, 0, -1, 1, -1]);
});

test("problems are named line by line", () => {
  const lines = [line(1, 5, "a"), line(4, 6, " "), line(3, 8, "c")];
  expect(lines.map((_, i) => lineIssue(lines, i))).toEqual([
    "Si sovrappone alla riga successiva", "Riga vuota: salvando viene tolta", "Comincia prima della riga precedente"]);
  expect(lineIssue(three(), 1)).toBeNull();
});

test("saving drops empty lines, tidies the text and keeps only word times that still fit", () => {
  const saved = forSave([
    line(5, 6.00049, "  due   parole ", [{ start: 5, end: 5.5, text: "x" }, { start: 5.5, end: 6, text: "y" }]),
    line(7, 8, "   "),
    line(1, 2, "prima", [{ start: 1, end: 2, text: "a" }, { start: 2, end: 2, text: "b" }]),
  ]);
  expect(saved).toEqual([
    line(1, 2, "prima"),
    line(5, 6, "due parole", [{ start: 5, end: 5.5, text: "due" }, { start: 5.5, end: 6, text: "parole" }]),
  ]);
});

test("clock times are written and read back", () => {
  expect([0, 9.994, 75.5, 599.999].map(formatClock)).toEqual(["0:00.00", "0:09.99", "1:15.50", "10:00.00"]);
  expect(["1:15.5", "1:15,50", "75.5", " 0:07 ", "3"].map(parseClock)).toEqual([75.5, 75.5, 75.5, 7, 3]);
  expect(["", "abc", "1:75", "1:2:3", "-4"].map(parseClock)).toEqual([null, null, null, null, null]);
});
