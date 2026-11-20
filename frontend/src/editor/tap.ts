// Sincronizzare battendo il tempo: si ascolta il brano e si tiene premuto un tasto
// mentre la riga (o la parola) viene cantata. Qui c'è solo la logica, senza audio
// né tastiera: a ogni pressione e rilascio corrisponde un elenco di righe nuovo.

import type { LyricLine, Note } from "../lib/types";
import { autoEnd, ensureWords, MIN_LINE_S, MIN_WORD_S, reshape, retime, roundTime, snapTime, tokens } from "./lines";

/** Un tocco più breve di così segna solo l'inizio: la fine si ricava da sola. */
export const HOLD_MIN_S = 0.25;
/** Un tocco entro questa distanza da un attacco di nota viene portato sull'attacco. */
export const SNAP_TAP_S = 0.15;

export type TapUnit = "line" | "word";

export interface TapOptions {
  unit: TapUnit;
  /** Le note del brano, ordinate per inizio: danno gli attacchi e le fini a cui agganciarsi. */
  notes: Note[];
  snap: boolean;
}

export interface TapCursor {
  /** La riga che aspetta il prossimo tocco. */
  line: number;
  /** La parola dentro la riga (solo battendo parola per parola). */
  word: number;
  /** L'istante dell'ultima pressione, finché il tasto resta giù. */
  downAt: number | null;
  /** La riga toccata di sfuggita la cui fine si decide al tocco successivo. */
  pending: number | null;
  /** Lo stesso per la parola precedente dentro la riga in corso. */
  wordPending: boolean;
}

export interface TapStep {
  lines: LyricLine[];
  cursor: TapCursor;
}

export const tapStart = (line: number): TapCursor => ({ line, word: 0, downAt: null, pending: null, wordPending: false });

/** Si torna indietro: all'inizio della riga in corso se era già cominciata, altrimenti alla precedente. */
export function tapBack(cursor: TapCursor): TapCursor {
  return tapStart(cursor.word > 0 || cursor.downAt !== null ? cursor.line : Math.max(0, cursor.line - 1));
}

const byWord = (line: LyricLine, options: TapOptions): boolean => options.unit === "word" && tokens(line.text).length > 0;

/** La riga con una fine nuova: battendo le parole è la fine dell'ultima parola. */
function withEnd(line: LyricLine, end: number, wordwise: boolean): LyricLine {
  if (!wordwise || !line.words || line.words.length === 0) {
    return reshape(line, line.start, Math.max(end, line.start + MIN_LINE_S));
  }
  const last = line.words[line.words.length - 1];
  const to = roundTime(Math.max(end, last.start + MIN_WORD_S));
  return { ...line, end: to, words: [...line.words.slice(0, -1), { ...last, end: to }] };
}

/** Le righe dopo `from` che comincerebbero prima della fine di quella che le precede le si accodano. */
function pushAhead(lines: LyricLine[], from: number): void {
  for (let i = from + 1; i < lines.length; i++) {
    const floor = lines[i - 1].end;
    if (lines[i].start >= floor) break;
    lines[i] = retime(lines[i], floor, floor + (lines[i].end - lines[i].start));
  }
}

/** Da dove la riga in sospeso misura la sua fine: dal suo inizio, o dall'ultima parola battuta. */
function anchorOf(line: LyricLine, wordwise: boolean): number {
  return wordwise && line.words && line.words.length > 0 ? line.words[line.words.length - 1].start : line.start;
}

/**
 * Comincia una riga a `start`: quella prima, se era in sospeso o non era ancora
 * finita, si chiude qui. Restituisce l'inizio effettivo.
 */
function closePrevious(lines: LyricLine[], cursor: TapCursor, start: number, options: TapOptions): number {
  const index = cursor.line;
  if (index === 0) return Math.max(start, 0);
  const previous = lines[index - 1];
  const wordwise = byWord(previous, options);
  const from = Math.max(start, previous.start + MIN_LINE_S);
  if (cursor.pending === index - 1) {
    lines[index - 1] = withEnd(previous, autoEnd(anchorOf(previous, wordwise), from, options.notes), wordwise);
  } else if (previous.end > from) {
    lines[index - 1] = reshape(previous, previous.start, from);   // le parole che sforano si fermano lì
  }
  return from;
}

/** Il tasto scende all'istante `t` del brano: comincia la riga (o la parola) che aspettava. */
export function tapDown(lines: LyricLine[], cursor: TapCursor, t: number, options: TapOptions): TapStep {
  if (cursor.downAt !== null || cursor.line >= lines.length) return { lines, cursor };
  const next = lines.slice();
  const index = cursor.line;
  let line = next[index];
  let at = options.snap ? snapTime(t, options.notes, "start", SNAP_TAP_S) : t;

  if (!byWord(line, options) || cursor.word === 0) {
    at = closePrevious(next, cursor, at, options);
    if (byWord(line, options)) line = { ...line, words: ensureWords(line) };
    next[index] = retime(line, at, at + (line.end - line.start));
    return { lines: next, cursor: { ...cursor, downAt: roundTime(at), pending: null, wordPending: false } };
  }

  // Una parola dopo la prima: quella prima finisce qui se era stata solo sfiorata, e le successive seguono il tocco.
  const words = ensureWords(line).slice();
  const k = cursor.word;
  const before = words[k - 1];
  at = roundTime(Math.max(at, before.start + MIN_WORD_S));
  if (cursor.wordPending || before.end > at) words[k - 1] = { ...before, end: at };
  const delta = at - words[k].start;
  for (let j = k; j < words.length; j++) {
    words[j] = { ...words[j], start: roundTime(words[j].start + delta), end: roundTime(words[j].end + delta) };
  }
  next[index] = { ...line, words, end: Math.max(words[words.length - 1].end, roundTime(line.start + MIN_LINE_S)) };
  return { lines: next, cursor: { ...cursor, downAt: at, wordPending: false } };
}

/** Il tasto sale all'istante `t`: se è rimasto giù abbastanza, lì finisce la riga (o la parola). */
export function tapUp(lines: LyricLine[], cursor: TapCursor, t: number, options: TapOptions): TapStep {
  if (cursor.downAt === null || cursor.line >= lines.length) return { lines, cursor };
  const next = lines.slice();
  const index = cursor.line;
  const line = next[index];
  const following = next[index + 1];
  const held = t - cursor.downAt >= HOLD_MIN_S;
  const release = options.snap ? snapTime(t, options.notes, "end", SNAP_TAP_S) : t;

  if (!byWord(line, options)) {
    if (held) {
      next[index] = reshape(line, line.start, Math.max(release, line.start + MIN_LINE_S));
    } else if (following && following.start > line.start + MIN_LINE_S && following.start < line.end) {
      next[index] = reshape(line, line.start, following.start);   // provvisoria: il prossimo tocco la sistema
    }
    pushAhead(next, index);
    return { lines: next, cursor: { ...tapStart(index + 1), pending: held ? null : index } };
  }

  const words = ensureWords(line).slice();
  const k = cursor.word;
  const last = k === words.length - 1;
  if (held) {
    const end = roundTime(Math.max(release, words[k].start + MIN_WORD_S));
    words[k] = { ...words[k], end };
    const delta = last ? 0 : end - words[k + 1].start;
    for (let j = k + 1; delta > 0 && j < words.length; j++) {
      words[j] = { ...words[j], start: roundTime(words[j].start + delta), end: roundTime(words[j].end + delta) };
    }
  } else {
    let end = Math.max(words[k].end, words[k].start + MIN_WORD_S);
    if (last && following && following.start > words[k].start + MIN_WORD_S) end = Math.min(end, following.start);
    words[k] = { ...words[k], end: roundTime(end) };
  }
  next[index] = { ...line, words, end: Math.max(words[words.length - 1].end, roundTime(line.start + MIN_LINE_S)) };
  if (!last) return { lines: next, cursor: { ...cursor, word: k + 1, downAt: null, wordPending: !held } };
  pushAhead(next, index);
  return { lines: next, cursor: { ...tapStart(index + 1), pending: held ? null : index } };
}

/** Si smette di battere: una riga rimasta in sospeso si chiude con l'ultima nota prima della successiva. */
export function tapFinish(lines: LyricLine[], cursor: TapCursor, options: TapOptions): LyricLine[] {
  if (cursor.pending === null || !lines[cursor.pending]) return lines;
  const index = cursor.pending;
  const line = lines[index];
  const wordwise = byWord(line, options);
  const anchor = anchorOf(line, wordwise);
  const following = lines[index + 1];
  const limit = following && following.start > anchor + MIN_LINE_S ? following.start : line.end;
  const next = lines.slice();
  next[index] = withEnd(line, autoEnd(anchor, limit, options.notes), wordwise);
  return next;
}
