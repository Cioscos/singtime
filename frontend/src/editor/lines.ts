// Le operazioni dell'editor sulle righe del testo. Sono funzioni pure: ogni modifica
// restituisce un elenco nuovo e lascia intatto quello di partenza, così annullare
// significa soltanto tornare all'elenco precedente.
//
// L'ordine dell'elenco è quello in cui le righe si cantano: nessuna operazione lo cambia.
// Una riga spostata o allungata contro la vicina la accorcia; non la scavalca mai.

import type { LyricLine, Note, Word } from "../lib/types";

/** Una riga non si può stringere più di così. */
export const MIN_LINE_S = 0.1;
/** Lo stesso per una parola. */
export const MIN_WORD_S = 0.02;
/** Due tempi più vicini di così sono lo stesso istante: un confine condiviso. */
export const LINK_S = 0.03;
/** Quanto dura una riga appena aggiunta, se c'è posto. */
const NEW_LINE_S = 2;
/** Sotto questo spazio una riga nuova non ci sta: si divide in due quella accanto. */
const MIN_ROOM_S = 0.3;
/** Dove nessuno canta, una riga con la fine automatica non dura più di così. */
const AUTO_END_MAX_S = 6;
/** Un silenzio della voce più lungo di così chiude la frase: la riga con la fine automatica si ferma lì. */
const PHRASE_GAP_S = 2.5;

export const roundTime = (t: number): number => Math.round(t * 1000) / 1000;

/** Come `Math.min(Math.max(...))`, ma se i limiti si incrociano vince quello basso. */
const clamp = (value: number, low: number, high: number): number => Math.max(low, Math.min(value, high));

const letters = (text: string): number => text.replace(/\s/g, "").length;

// --- parole ------------------------------------------------------------------

export function tokens(text: string): string[] {
  const trimmed = text.trim();
  return trimmed ? trimmed.split(/\s+/) : [];
}

/**
 * I tempi delle parole, se valgono ancora per il testo della riga: tante parole
 * quante ne ha il testo, che può essere stato corretto nel frattempo. Altrimenti null.
 */
export function wordsOf(line: LyricLine): Word[] | null {
  if (!line.words || line.words.length === 0) return null;
  const texts = tokens(line.text);
  if (texts.length !== line.words.length) return null;
  return line.words.map((word, i) => (word.text === texts[i] ? word : { ...word, text: texts[i] }));
}

/** Parole stimate: si dividono la riga in proporzione alla lunghezza. */
export function spreadWords(line: LyricLine): Word[] {
  const texts = tokens(line.text);
  const total = texts.reduce((sum, text) => sum + text.length, 0);
  const duration = Math.max(0, line.end - line.start);
  let done = 0;
  return texts.map((text) => {
    const start = line.start + (duration * done) / total;
    done += text.length;
    return { start: roundTime(start), end: roundTime(line.start + (duration * done) / total), text };
  });
}

/** I tempi delle parole della riga: quelli veri se ci sono, altrimenti stimati. */
export function ensureWords(line: LyricLine): Word[] {
  return wordsOf(line) ?? spreadWords(line);
}

// --- tempi di una riga -------------------------------------------------------

/** La riga portata tra `start` ed `end`; le parole la seguono in proporzione. */
export function retime(line: LyricLine, start: number, end: number): LyricLine {
  const before = line.end - line.start;
  const scale = before > 0 ? (end - start) / before : 0;
  const map = (t: number) => roundTime(start + (t - line.start) * scale);
  return {
    ...line,
    start: roundTime(start),
    end: roundTime(end),
    words: line.words?.map((word) => ({ ...word, start: map(word.start), end: map(word.end) })) ?? null,
  };
}

function replaced(lines: LyricLine[], index: number, line: LyricLine): LyricLine[] {
  const next = lines.slice();
  next[index] = line;
  return next;
}

/**
 * La riga con inizio e fine nuovi, senza toccare le parole in mezzo: segue solo
 * quella attaccata al bordo che si sposta, e nessuna resta fuori dalla riga.
 */
export function reshape(line: LyricLine, start: number, end: number): LyricLine {
  const last = (line.words?.length ?? 0) - 1;
  return {
    ...line,
    start: roundTime(start),
    end: roundTime(end),
    words: line.words?.map((word, i) => {
      const from = clamp(i === 0 && Math.abs(word.start - line.start) < LINK_S ? start : word.start, start, end);
      const to = clamp(i === last && Math.abs(word.end - line.end) < LINK_S ? end : word.end, from, end);
      return { ...word, start: roundTime(from), end: roundTime(to) };
    }) ?? null,
  };
}

/** Fin dove la riga può arrivare: contro le vicine le accorcia, ma non le fa sparire. */
function limits(lines: LyricLine[], index: number, songDuration: number): { floor: number; ceiling: number } {
  const line = lines[index];
  const previous = lines[index - 1];
  const following = lines[index + 1];
  return {
    floor: previous ? Math.min(previous.start + MIN_LINE_S, line.start) : 0,
    ceiling: following ? Math.max(following.end - MIN_LINE_S, line.end) : Math.max(songDuration, line.end),
  };
}

/**
 * Mette la riga nuova al posto di quella all'indice e sistema le vicine: una
 * riga che entra nella vicina la accorcia. Con `linked` il bordo della vicina
 * segue in entrambi i versi: è il confine tra le due righe.
 */
function settle(lines: LyricLine[], index: number, line: LyricLine, linked: "start" | "end" | null = null): LyricLine[] {
  const before = lines[index];
  if (line.start === before.start && line.end === before.end) return lines;
  const next = replaced(lines, index, line);
  const previous = lines[index - 1];
  const following = lines[index + 1];
  if (previous && line.start !== before.start && (linked === "start" || line.start < Math.min(previous.end, before.start))) {
    next[index - 1] = reshape(previous, previous.start, line.start);
  }
  if (following && line.end !== before.end && (linked === "end" || line.end > Math.max(following.start, before.end))) {
    next[index + 1] = reshape(following, line.end, following.end);
  }
  return next;
}

/** Sposta la riga senza cambiarne la durata. */
export function moveLine(lines: LyricLine[], index: number, start: number, songDuration: number): LyricLine[] {
  const line = lines[index];
  const { floor, ceiling } = limits(lines, index, songDuration);
  const duration = line.end - line.start;
  const to = clamp(start, floor, ceiling - duration);
  return settle(lines, index, retime(line, to, to + duration));
}

/** Sposta l'inizio della riga; con `linked` la fine della riga precedente lo segue. */
export function resizeStart(lines: LyricLine[], index: number, start: number, songDuration: number, linked = false): LyricLine[] {
  const line = lines[index];
  const to = Math.min(Math.max(start, limits(lines, index, songDuration).floor), line.end - MIN_LINE_S);
  return settle(lines, index, reshape(line, to, line.end), linked ? "start" : null);
}

/** Sposta la fine della riga; con `linked` l'inizio della riga successiva la segue. */
export function resizeEnd(lines: LyricLine[], index: number, end: number, songDuration: number, linked = false): LyricLine[] {
  const line = lines[index];
  const to = clamp(end, line.start + MIN_LINE_S, limits(lines, index, songDuration).ceiling);
  return settle(lines, index, reshape(line, line.start, to), linked ? "end" : null);
}

/**
 * "La riga comincia qui": se l'istante cade dentro la riga se ne sposta solo
 * l'inizio, se cade dopo la riga si sposta tutta. La riga precedente, se a
 * quell'istante non era ancora finita, viene accorciata: chi segna l'inizio sa
 * quello che sente.
 */
export function markStart(lines: LyricLine[], index: number, t: number, songDuration: number): LyricLine[] {
  const line = lines[index];
  const next = lines.slice();
  let start = Math.max(t, 0);
  if (index > 0) {
    const previous = lines[index - 1];
    start = Math.max(start, previous.start + MIN_LINE_S);
    if (previous.end > start) next[index - 1] = reshape(previous, previous.start, start);
  }
  if (start < line.end - MIN_LINE_S) {
    next[index] = reshape(line, start, line.end);
  } else {
    const following = lines[index + 1];
    const ceiling = following ? Math.max(following.start, line.end) : Math.max(songDuration, line.end);
    start = Math.min(start, ceiling - MIN_LINE_S);
    next[index] = retime(line, start, Math.min(start + (line.end - line.start), ceiling));
  }
  return next;
}

/** Sposta tutte le righe insieme; la prima non scende sotto lo zero. */
export function shiftAll(lines: LyricLine[], delta: number): LyricLine[] {
  if (lines.length === 0) return lines;
  const first = Math.min(...lines.map((line) => line.start));
  const by = Math.max(delta, -first);
  if (roundTime(by) === 0) return lines;
  return lines.map((line) => retime(line, line.start + by, line.end + by));
}

// --- parole sulla timeline ---------------------------------------------------

/**
 * Sposta un bordo di una parola. Con `linked` il bordo della parola accanto,
 * se combacia, si sposta insieme: è il confine tra le due.
 */
export function moveWordEdge(lines: LyricLine[], index: number, word: number, edge: "start" | "end",
                             t: number, linked: boolean): LyricLine[] {
  const line = lines[index];
  const words = wordsOf(line);
  if (!words || !words[word]) return lines;
  const next = words.slice();
  const current = words[word];
  if (edge === "start") {
    const previous = words[word - 1];
    const low = previous ? (linked ? previous.start + MIN_WORD_S : previous.end) : line.start;
    const to = roundTime(clamp(t, low, current.end - MIN_WORD_S));
    next[word] = { ...current, start: to };
    if (previous && linked) next[word - 1] = { ...previous, end: to };
  } else {
    const following = words[word + 1];
    const high = following ? (linked ? following.end - MIN_WORD_S : following.start) : line.end;
    const to = roundTime(Math.min(Math.max(t, current.start + MIN_WORD_S), Math.max(high, current.start + MIN_WORD_S)));
    next[word] = { ...current, end: to };
    if (following && linked) next[word + 1] = { ...following, start: to };
  }
  return replaced(lines, index, { ...line, words: next });
}

// --- testo, righe aggiunte e tolte -------------------------------------------

/** Cambia solo il testo: i tempi delle parole si riconciliano dopo (vedi `wordsOf`). */
export function setText(lines: LyricLine[], index: number, text: string): LyricLine[] {
  return lines[index].text === text ? lines : replaced(lines, index, { ...lines[index], text });
}

/**
 * Divide la riga dove sta il cursore del testo. Il tempo si divide tra due
 * parole se i loro tempi sono noti, altrimenti in proporzione alle lettere.
 * Null se una delle due metà resterebbe vuota.
 */
export function splitLine(lines: LyricLine[], index: number, caret: number): LyricLine[] | null {
  const line = lines[index];
  const left = line.text.slice(0, caret).trim();
  const right = line.text.slice(caret).trim();
  if (!left || !right) return null;
  const words = wordsOf(line);
  const leftCount = tokens(left).length;
  let first: LyricLine;
  let second: LyricLine;
  if (words && leftCount + tokens(right).length === words.length) {
    const leftWords = words.slice(0, leftCount);
    const rightWords = words.slice(leftCount);
    const cut = rightWords[0].start;
    first = { start: line.start, end: Math.max(line.start, Math.min(leftWords[leftWords.length - 1].end, cut)), text: left, words: leftWords };
    second = { start: Math.min(cut, line.end), end: line.end, text: right, words: rightWords };
  } else {
    const cut = roundTime(line.start + ((line.end - line.start) * letters(left)) / (letters(left) + letters(right)));
    first = { start: line.start, end: cut, text: left, words: null };
    second = { start: cut, end: line.end, text: right, words: null };
  }
  return [...lines.slice(0, index), first, second, ...lines.slice(index + 1)];
}

/**
 * Unisce la riga alla successiva. `caret` è il punto del testo unito in cui
 * finiva la prima: lì va rimesso il cursore. Una riga vuota sparisce e basta.
 */
export function mergeLines(lines: LyricLine[], index: number): { lines: LyricLine[]; caret: number } | null {
  const first = lines[index];
  const second = lines[index + 1];
  if (!first || !second) return null;
  const a = first.text.trim();
  const b = second.text.trim();
  let merged: LyricLine;
  if (!a) merged = second;
  else if (!b) merged = first;
  else {
    const firstWords = wordsOf(first);
    const secondWords = wordsOf(second);
    merged = {
      start: first.start,
      end: Math.max(first.end, second.end),
      text: `${a} ${b}`,
      words: firstWords && secondWords ? [...firstWords, ...secondWords] : null,
    };
  }
  return {
    lines: [...lines.slice(0, index), merged, ...lines.slice(index + 2)],
    caret: !a ? 0 : !b ? first.text.length : a.length + 1,
  };
}

export function removeLine(lines: LyricLine[], index: number): LyricLine[] {
  return lines.filter((_, i) => i !== index);
}

const emptyLine = (start: number, end: number): LyricLine => ({ start: roundTime(start), end: roundTime(end), text: "", words: null });

/**
 * Una riga vuota dopo la riga `after` (-1: in cima), nello spazio libero fino
 * alla successiva. Se lo spazio non c'è, la riga accanto le cede metà del suo tempo.
 */
export function addLineAfter(lines: LyricLine[], after: number, songDuration: number): { lines: LyricLine[]; index: number } {
  const previous = lines[after];
  const following = lines[after + 1];
  const from = previous ? previous.end : 0;
  const until = following ? following.start : Math.max(songDuration, from + NEW_LINE_S);
  const next = lines.slice();
  if (until - from >= MIN_ROOM_S) {
    next.splice(after + 1, 0, emptyLine(from, Math.min(from + NEW_LINE_S, until)));
  } else if (previous) {
    const middle = (previous.start + previous.end) / 2;
    next[after] = retime(previous, previous.start, middle);
    next.splice(after + 1, 0, emptyLine(middle, previous.end));
  } else {
    const middle = (following.start + following.end) / 2;
    next[0] = retime(following, middle, following.end);
    next.splice(0, 0, emptyLine(following.start, middle));
  }
  return { lines: next, index: after + 1 };
}

/** Una riga vuota che comincia all'istante `t`, se lì c'è posto; altrimenti dopo la riga che occupa quell'istante. */
export function addLineAt(lines: LyricLine[], t: number, songDuration: number): { lines: LyricLine[]; index: number } {
  let after = -1;
  while (after + 1 < lines.length && lines[after + 1].start <= t) after++;
  const following = lines[after + 1];
  const until = following ? following.start : Math.max(songDuration, t + NEW_LINE_S);
  const free = after < 0 || t >= lines[after].end;
  if (!free || until - t < MIN_ROOM_S) return addLineAfter(lines, after, songDuration);
  const next = lines.slice();
  next.splice(after + 1, 0, emptyLine(t, Math.min(t + NEW_LINE_S, until)));
  return { lines: next, index: after + 1 };
}

/** Righe provvisorie per un testo senza tempi: distribuite dove si canta, da sistemare poi a orecchio. */
export function distribute(texts: string[], notes: Note[], songDuration: number): LyricLine[] {
  if (texts.length === 0) return [];
  let from = notes.length > 0 ? notes[0].start : 0;
  let until = notes.length > 0 ? notes[notes.length - 1].start + notes[notes.length - 1].duration : songDuration;
  if (until - from < texts.length * 0.5) {
    from = 0;
    until = Math.max(songDuration, texts.length);
  }
  const slot = (until - from) / texts.length;
  return texts.map((text, i) => ({
    start: roundTime(from + i * slot), end: roundTime(from + i * slot + slot * 0.9), text, words: null,
  }));
}

// --- le note come riferimento ------------------------------------------------

/**
 * Dove finisce una riga che comincia a `start` e deve lasciare il posto a `limit`:
 * con l'ultima nota della frase cantata in quel tratto, cioè prima che la voce
 * taccia a lungo. `notes` è ordinato per inizio.
 */
export function autoEnd(start: number, limit: number, notes: Note[]): number {
  let end = -Infinity;
  for (const note of notes) {
    if (note.start >= limit) break;
    if (note.start + note.duration <= start) continue;
    // Un canto che arriva dopo un lungo silenzio non è più di questa riga.
    if (note.start - (end === -Infinity ? start : end) > (end === -Infinity ? AUTO_END_MAX_S : PHRASE_GAP_S)) break;
    end = Math.max(end, note.start + note.duration);
  }
  if (end === -Infinity) end = Math.min(limit, start + AUTO_END_MAX_S);
  return roundTime(Math.max(Math.min(end, limit), start + MIN_LINE_S));
}

/** L'inizio (o la fine) di nota più vicino a `t`, se sta entro `tolerance` secondi; altrimenti `t`. */
export function snapTime(t: number, notes: Note[], edge: "start" | "end", tolerance: number): number {
  let best = t;
  let distance = tolerance;
  for (const note of notes) {
    const at = edge === "start" ? note.start : note.start + note.duration;
    if (Math.abs(at - t) <= distance) {
      best = at;
      distance = Math.abs(at - t);
    }
  }
  return best;
}

// --- controlli e salvataggio -------------------------------------------------

/** La riga che si canta all'istante `t`, o -1. */
export function lineIndexAt(lines: LyricLine[], t: number): number {
  for (let i = lines.length - 1; i >= 0; i--) {
    if (lines[i].start <= t) return t < lines[i].end ? i : -1;
  }
  return -1;
}

/** Che cosa non va in una riga, da mostrare accanto; null se è a posto. */
export function lineIssue(lines: LyricLine[], index: number): string | null {
  const line = lines[index];
  if (!line.text.trim()) return "Riga vuota: salvando viene tolta";
  if (index > 0 && line.start < lines[index - 1].start) return "Comincia prima della riga precedente";
  if (index + 1 < lines.length && line.end > lines[index + 1].start + 0.001) return "Si sovrappone alla riga successiva";
  return null;
}

/** Le righe come vanno salvate: senza quelle vuote, in ordine di tempo, con le parole che valgono ancora. */
export function forSave(lines: LyricLine[]): LyricLine[] {
  return lines
    .filter((line) => line.text.trim())
    .map((line) => ({
      start: roundTime(Math.max(0, line.start)),
      end: roundTime(Math.max(line.end, line.start, 0)),
      text: tokens(line.text).join(" "),
      words: wordsOf(line)?.map((word) => ({
        start: roundTime(Math.max(0, word.start)), end: roundTime(Math.max(word.end, word.start, 0)), text: word.text,
      })) ?? null,
    }))
    .sort((a, b) => a.start - b.start);
}

// --- tempi scritti -----------------------------------------------------------

/** 75.5 → "1:15.50" */
export function formatClock(seconds: number): string {
  const hundredths = Math.round(Math.max(0, seconds) * 100);
  const minutes = Math.floor(hundredths / 6000);
  return `${minutes}:${((hundredths - minutes * 6000) / 100).toFixed(2).padStart(5, "0")}`;
}

/** "1:15.5", "1:15,5" o "75.5" → secondi; null se non è un tempo. */
export function parseClock(text: string): number | null {
  const match = /^(?:(\d+):)?(\d+(?:[.,]\d+)?)$/.exec(text.trim());
  if (!match) return null;
  const seconds = Number(match[2].replace(",", "."));
  if (match[1] !== undefined && seconds >= 60) return null;
  return Number(match[1] ?? 0) * 60 + seconds;
}
