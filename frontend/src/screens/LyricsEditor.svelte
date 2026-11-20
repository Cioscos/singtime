<script lang="ts">
  // L'editor del testo: si ascolta il brano, si vede la voce lungo il tempo e si
  // sistemano righe e parole trascinandole, segnandole al volo o battendo il tempo.
  import { onMount, tick } from "svelte";
  import { History } from "../editor/history";
  import {
    addLineAfter, addLineAt, forSave, formatClock, lineIndexAt, lineIssue, LINK_S, markStart, mergeLines, moveLine,
    moveWordEdge, parseClock, removeLine, resizeEnd, resizeStart, setText, shiftAll, snapTime, splitLine, tokens, wordsOf,
  } from "../editor/lines";
  import { formatLrc, linesFromPaste, pasteKind } from "../editor/lrc";
  import { SNAP_TAP_S, tapBack, tapDown, tapFinish, tapStart, tapUp, type TapCursor, type TapUnit } from "../editor/tap";
  import {
    clampView, cursorFor, drawTimeline, followView, hitTest, TIMELINE_HEIGHT, xToTime, zoomView, type View,
  } from "../editor/timeline";
  import { pitchRange, type PitchRange } from "../game/layout";
  import { lineAt, wordSpan } from "../game/lyrics-progress";
  import { ApiError, audioUrl, getLyrics, getNotes, getWaveform, putLyrics, type AudioTrack } from "../lib/api";
  import type { LyricLine, Note, Song } from "../lib/types";

  let { song, active, dirty = $bindable(false), onsaved }: {
    song: Song;
    /** Falso quando la schermata mostra altro: niente tastiera, niente audio. */
    active: boolean;
    /** Vero se ci sono modifiche non salvate. */
    dirty?: boolean;
    onsaved: () => void;
  } = $props();

  const TRACKS: { value: AudioTrack; label: string }[] = [
    { value: "source", label: "Brano intero" },
    { value: "vocals", label: "Solo voce" },
    { value: "instrumental", label: "Solo base" },
  ];
  const RATES = [0.5, 0.75, 1];
  const SEEK_S = 2;
  const NUDGE_S = 0.05;
  const SHIFT_S = 0.1;
  /** Trascinando, un bordo si aggancia a una nota entro questi pixel. */
  const SNAP_PX = 8;
  /** Battendo il tempo si riparte al più questi secondi prima della riga. */
  const TAP_LEAD_S = 4;

  type Drag =
    | { kind: "scrub" }
    | { kind: "line"; part: "start" | "end" | "body"; index: number; linked: boolean; origin: LyricLine[]; grab: number; x: number; moved: boolean }
    | { kind: "word"; index: number; word: number; edge: "start" | "end"; linked: boolean; origin: LyricLine[]; x: number; moved: boolean };

  interface Preview {
    before: string;
    word: string;
    after: string;
    next: string;
  }

  // Elenchi sostituiti a ogni modifica, mai cambiati sul posto: senza proxy profondi.
  let lines = $state.raw<LyricLine[]>([]);
  let saved = $state.raw<LyricLine[]>([]);
  let notes = $state.raw<Note[]>([]);
  let selected = $state(-1);
  let playingLine = $state(-1);
  let loaded = $state(false);
  let broken = $state("");
  let error = $state("");
  let notice = $state("");
  let saving = $state(false);
  let playing = $state(false);
  let track = $state<AudioTrack>("source");
  let rate = $state(1);
  let snap = $state(true);
  let clock = $state("0:00.00");
  let preview = $state.raw<Preview | null>(null);
  let tap = $state.raw<TapCursor | null>(null);
  let tapUnit = $state<TapUnit>("line");
  let canUndo = $state(false);
  let canRedo = $state(false);
  let pasteOpen = $state(false);
  let pasteText = $state("");
  let audioDuration = $state(0);

  let root = $state<HTMLDivElement>();
  let canvas = $state<HTMLCanvasElement>();
  let audio = $state<HTMLAudioElement>();
  let list = $state<HTMLDivElement>();
  let dialog = $state<HTMLDialogElement>();

  // Quello che serve solo al disegno non passa dalla reattività: cambia a ogni fotogramma.
  let view: View = { start: 0, span: 20, width: 1 };
  let peaks: Uint8Array | null = null;
  let peakRate = 100;
  let range: PitchRange = pitchRange([]);
  let ctx: AudioContext | null = null;
  let stopAt: number | null = null;
  let drag: Drag | null = null;
  let tapOrigin: LyricLine[] = [];
  let frame = 0;
  const history = new History<LyricLine[]>();

  const duration = $derived(song.duration_s ?? audioDuration);
  const current = $derived(lines[selected] ?? null);
  const issues = $derived(lines.map((_, i) => lineIssue(lines, i)));
  const paste = $derived(pasteKind(pasteText, lines));
  const pasteHint = $derived.by(() => {
    if (paste.count === 0) return "";
    const rows = paste.count === 1 ? "1 riga" : `${paste.count} righe`;
    if (paste.kind === "timed") return `${rows} con i tempi: prendono il posto del testo attuale.`;
    if (paste.kind === "kept") return `${rows}, come adesso: cambiano le parole, i tempi restano.`;
    return `${rows} senza tempi: le distribuisco lungo il brano, poi si sincronizzano con «Batti il tempo».`;
  });

  $effect(() => {
    dirty = lines !== saved;
  });

  $effect(() => {
    if (!audio) return;
    audio.defaultPlaybackRate = rate;
    audio.playbackRate = rate;
  });

  $effect(() => {
    if (!active) audio?.pause();
  });

  // Durante l'ascolto l'elenco segue la riga cantata, a meno che non si stia scrivendo.
  $effect(() => {
    const index = playingLine;
    if (index < 0 || !playing || tap) return;
    if (list?.contains(document.activeElement)) return;
    rowOf(index)?.scrollIntoView({ block: "nearest" });
  });

  onMount(() => {
    load();
    frame = requestAnimationFrame(loop);
    return () => {
      cancelAnimationFrame(frame);
      ctx?.close();
    };
  });

  async function load() {
    try {
      const [rawLines, loadedNotes] = await Promise.all([
        // "Non c'è ancora" è un brano senza testo; qualsiasi altro errore no: salvando si perderebbe quello vero.
        getLyrics(song.id).catch((e) => {
          if (e instanceof ApiError && e.status === 404) return [] as LyricLine[];
          throw e;
        }),
        getNotes(song.id).catch(() => [] as Note[]),
      ]);
      notes = loadedNotes;
      range = pitchRange(loadedNotes);
      // Lo spostamento globale si vede già applicato: salvando entra nei tempi delle righe.
      lines = saved = shiftAll(rawLines, song.lyrics_offset_s);
      selected = lines.length > 0 ? 0 : -1;
      view = { ...view, start: Math.max(0, (lines[0]?.start ?? loadedNotes[0]?.start ?? 0) - 2) };
      loaded = true;
    } catch (e) {
      broken = (e as Error).message;
    }
    getWaveform(song.id)
      .then((waveform) => {
        peaks = Uint8Array.from(waveform.peaks);
        peakRate = waveform.rate;
      })
      .catch(() => {});   // senza il profilo della voce restano le note
  }

  // --- modifiche, annulla e ripeti ---------------------------------------------

  function syncHistory() {
    canUndo = history.canUndo;
    canRedo = history.canRedo;
  }

  function commit(next: LyricLine[], key: string | null = null) {
    if (next === lines) return;
    history.record(lines, key);
    lines = next;
    notice = "";
    syncHistory();
  }

  function restore(state: LyricLine[] | undefined) {
    if (!state) return;
    lines = state;
    if (selected >= lines.length) selected = lines.length - 1;
    syncHistory();
  }
  const undo = () => restore(history.undo(lines));
  const redo = () => restore(history.redo(lines));

  // --- selezione e campi di testo ----------------------------------------------

  const rowOf = (index: number) => list?.children[index] as HTMLElement | undefined;
  const inputOf = (index: number) => rowOf(index)?.querySelector<HTMLInputElement>("input.text") ?? null;

  function select(index: number) {
    if (index < 0 || index >= lines.length) return;
    selected = index;
    rowOf(index)?.scrollIntoView({ block: "nearest" });
    // A brano fermo la timeline va alla riga scelta; in riproduzione segue già l'audio.
    if (audio?.paused) view = followView(view, lines[index].start, duration);
  }

  async function focusText(index: number, caret: number | null = null) {
    if (index < 0 || index >= lines.length) return;
    selected = index;
    await tick();
    const input = inputOf(index);
    if (!input) return;
    input.focus();
    const at = Math.min(caret ?? input.value.length, input.value.length);
    input.setSelectionRange(at, at);
    rowOf(index)?.scrollIntoView({ block: "nearest" });
  }

  function onText(index: number, value: string) {
    commit(setText(lines, index, value), `text:${index}`);
  }

  function splitAt(index: number, caret: number) {
    const split = splitLine(lines, index, caret);
    if (split) {
      commit(split);
      focusText(index + 1, 0);
    } else if (lines[index].text.slice(caret).trim() === "") {
      // In fondo alla riga: come andare a capo, comincia una riga nuova.
      const added = addLineAfter(lines, index, duration);
      commit(added.lines);
      focusText(added.index, 0);
    }
  }

  function mergeAt(index: number) {
    const merged = mergeLines(lines, index);
    if (!merged) return;
    commit(merged.lines);
    focusText(index, merged.caret);
  }

  function onTextKey(event: KeyboardEvent, index: number) {
    if (event.ctrlKey || event.metaKey || event.altKey) return;
    const input = event.currentTarget as HTMLInputElement;
    const caret = input.selectionStart ?? 0;
    const collapsed = caret === input.selectionEnd;
    if (event.key === "Enter") {
      event.preventDefault();
      splitAt(index, caret);
    } else if (event.key === "Backspace" && collapsed && caret === 0 && index > 0) {
      event.preventDefault();
      mergeAt(index - 1);
    } else if (event.key === "Delete" && collapsed && caret === input.value.length && index + 1 < lines.length) {
      event.preventDefault();
      mergeAt(index);
    } else if (event.key === "ArrowUp" && index > 0) {
      event.preventDefault();
      focusText(index - 1, caret);
    } else if (event.key === "ArrowDown" && index + 1 < lines.length) {
      event.preventDefault();
      focusText(index + 1, caret);
    } else if (event.key === "Escape") {
      input.blur();
    }
  }

  // --- audio -------------------------------------------------------------------

  /** L'istante del brano che si sta sentendo: l'uscita audio arriva con un po' di ritardo. */
  function heard(): number {
    if (!audio) return 0;
    if (audio.paused || !ctx) return audio.currentTime;
    const latency = (ctx.outputLatency || 0) + (ctx.baseLatency || 0);
    return Math.max(0, audio.currentTime - latency * audio.playbackRate);
  }

  // L'audio passa da un AudioContext solo per conoscerne il ritardo d'uscita, come nel gioco.
  function ensureContext() {
    if (ctx || !audio) return;
    try {
      const created = new AudioContext();
      created.createMediaElementSource(audio).connect(created.destination);
      ctx = created;
    } catch {
      ctx = null;   // si ascolta lo stesso, senza correzione del ritardo
    }
  }

  async function play() {
    if (!audio) return;
    ensureContext();
    try {
      await ctx?.resume();
      await audio.play();
    } catch {
      error = "Non riesco a riprodurre l'audio di questo brano.";
    }
  }

  function seek(t: number) {
    if (!audio) return;
    stopAt = null;
    audio.currentTime = Math.min(Math.max(t, 0), duration);
    // Saltando con i tasti il cursore non esce di vista; trascinandolo sulla timeline la vista resta ferma.
    if (!drag) view = followView(view, audio.currentTime, duration);
  }

  function togglePlay() {
    if (!audio) return;
    if (!audio.paused) return audio.pause();
    stopAt = null;
    play();
  }

  function playLine(index: number) {
    const line = lines[index];
    if (!line || !audio) return;
    audio.currentTime = line.start;
    stopAt = line.end;
    play();
  }

  async function switchTrack(next: AudioTrack) {
    if (!audio || next === track) return;
    const time = audio.currentTime;
    const wasPlaying = !audio.paused;
    track = next;
    await tick();
    audio.currentTime = time;
    audio.playbackRate = rate;
    if (wasPlaying) play();
  }

  function onAudioError() {
    // I brani elaborati con le prime versioni possono non avere più il brano intero.
    if (track === "source") switchTrack("vocals");
    else error = "Non riesco a caricare l'audio di questo brano.";
  }

  // --- la riga selezionata -----------------------------------------------------

  /** L'istante da segnare: mentre si ascolta, chi preme arriva un filo dopo l'attacco. */
  function markTime(edge: "start" | "end"): number {
    const now = heard();
    return snap && audio && !audio.paused ? snapTime(now, notes, edge, SNAP_TAP_S) : now;
  }

  function startHere() {
    if (current) commit(markStart(lines, selected, markTime("start"), duration));
  }

  function endHere() {
    if (current) commit(resizeEnd(lines, selected, markTime("end"), duration));
  }

  function nudge(delta: number) {
    if (current) commit(moveLine(lines, selected, current.start + delta, duration), `nudge:${selected}`);
  }

  function editTime(event: Event, edge: "start" | "end") {
    const input = event.currentTarget as HTMLInputElement;
    const t = parseClock(input.value);
    if (current && t !== null) {
      commit(edge === "start" ? resizeStart(lines, selected, t, duration) : resizeEnd(lines, selected, t, duration));
    }
    input.value = formatClock(lines[selected]?.[edge] ?? 0);   // quello che vale davvero, anche se il tempo scritto non andava
    input.blur();
  }

  function splitSelected() {
    const input = inputOf(selected);
    if (!current || !input) return;
    const before = lines;
    splitAt(selected, input.selectionStart ?? 0);
    if (lines === before) notice = "Metti il cursore nel punto del testo in cui dividere la riga.";
  }

  function addLine() {
    const now = heard();
    // Dove sta il cursore dell'audio, se lì non c'è già una riga; altrimenti dopo quella selezionata.
    const added = lineIndexAt(lines, now) >= 0 && selected >= 0
      ? addLineAfter(lines, selected, duration)
      : addLineAt(lines, now, duration);
    commit(added.lines);
    focusText(added.index, 0);
  }

  function removeSelected() {
    if (!current) return;
    commit(removeLine(lines, selected));
    selected = Math.min(selected, lines.length - 1);
  }

  // --- tutto il testo ----------------------------------------------------------

  function shiftEverything(delta: number) {
    commit(shiftAll(lines, delta), "shift");
  }

  function openPaste() {
    pasteText = lines.map((line) => line.text).join("\n");
    pasteOpen = true;
    dialog?.showModal();
  }

  function applyPaste() {
    commit(linesFromPaste(pasteText, lines, notes, duration));
    dialog?.close();
    selected = lines.length > 0 ? 0 : -1;
    if (lines.length > 0) view = clampView({ ...view, start: lines[0].start - 2 }, duration);
  }

  function exportLrc() {
    const url = URL.createObjectURL(new Blob([formatLrc(forSave(lines))], { type: "text/plain;charset=utf-8" }));
    const link = document.createElement("a");
    link.href = url;
    link.download = `${[song.artist, song.title].filter(Boolean).join(" - ") || "testo"}.lrc`.replace(/[\\/:*?"<>|]/g, "_");
    link.click();
    URL.revokeObjectURL(url);
  }

  async function save() {
    if (saving || !dirty || tap) return;
    saving = true;
    try {
      lines = saved = await putLyrics(song.id, forSave(lines));
      if (selected >= lines.length) selected = lines.length - 1;
      error = "";
      notice = "Testo salvato.";
      onsaved();
    } catch (e) {
      error = (e as Error).message;
    } finally {
      saving = false;
    }
  }

  // --- battere il tempo --------------------------------------------------------

  const tapOptions = () => ({ unit: tapUnit, notes, snap });

  function startTap() {
    if (!audio || lines.length === 0 || tap) return;
    (document.activeElement as HTMLElement | null)?.blur();
    const from = Math.max(selected, 0);
    tapOrigin = lines;
    tap = tapStart(from);
    select(from);
    // Si parte poco prima della riga, per sentirne l'attacco arrivare; se l'audio è già lì resta dov'è.
    const previous = lines[from - 1];
    const lead = previous ? Math.max(previous.start, previous.end - TAP_LEAD_S) : Math.max(0, lines[from].start - TAP_LEAD_S);
    const until = lines[from].start - (previous ? 0 : 1);
    if (audio.currentTime < lead || audio.currentTime > until) audio.currentTime = lead;
    stopAt = null;
    play();
  }

  function tapPress() {
    if (!tap || !audio || audio.paused) return;
    ({ lines, cursor: tap } = tapDown(lines, tap, heard(), tapOptions()));
  }

  function tapRelease() {
    if (!tap || tap.downAt === null) return;
    ({ lines, cursor: tap } = tapUp(lines, tap, heard(), tapOptions()));
    if (tap.line >= lines.length) stopTap();
    else if (tap.line !== selected) select(tap.line);
  }

  function tapStepBack() {
    if (!tap || !audio) return;
    tap = tapBack(tap);
    select(tap.line);
    audio.currentTime = Math.max(0, lines[tap.line].start - TAP_LEAD_S);
  }

  function stopTap() {
    if (!tap) return;
    audio?.pause();
    lines = tapFinish(lines, tap, tapOptions());
    const last = Math.min(tap.line, lines.length - 1);
    tap = null;
    // Tutta la sessione si annulla in un colpo solo.
    if (lines !== tapOrigin) {
      history.record(tapOrigin);
      notice = "";
      syncHistory();
    }
    select(last);
  }

  // --- tastiera ----------------------------------------------------------------

  function onKeyDown(event: KeyboardEvent) {
    if (!active || pasteOpen || !loaded) return;
    if (tap) {
      if (event.code === "Space") {
        event.preventDefault();
        if (!event.repeat) tapPress();
      } else if (event.key === "Escape") {
        event.preventDefault();
        stopTap();
      } else if (event.key === "Backspace") {
        event.preventDefault();
        tapStepBack();
      } else if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
        event.preventDefault();   // per saltare uno stacco strumentale, o riascoltare
        seek(heard() + (event.key === "ArrowLeft" ? -SEEK_S : SEEK_S));
      }
      return;
    }
    const key = event.key.toLowerCase();
    if (event.ctrlKey || event.metaKey) {
      if (key === "s") save();
      else if (key === "z" && !event.shiftKey) undo();
      else if (key === "y" || (key === "z" && event.shiftKey)) redo();
      else if (event.code === "Space") togglePlay();
      else return;
      event.preventDefault();
      return;
    }
    // Dentro un campo o su un pulsante i tasti fanno il loro mestiere.
    if (event.altKey || (event.target as HTMLElement).closest("input, textarea, select, button, a, summary")) return;
    if (event.code === "Space") togglePlay();
    else if (key === "arrowleft") seek(heard() - (event.shiftKey ? 0.5 : SEEK_S));
    else if (key === "arrowright") seek(heard() + (event.shiftKey ? 0.5 : SEEK_S));
    else if (key === "arrowup") select(Math.max(selected - 1, 0));
    else if (key === "arrowdown") select(Math.min(selected + 1, lines.length - 1));
    else if (key === "i") startHere();
    else if (key === "o") endHere();
    else if (key === "r") playLine(selected);
    else if (key === "enter") focusText(selected);
    else if (key === ",") nudge(-NUDGE_S);
    else if (key === ".") nudge(NUDGE_S);
    else if (key === "n") addLine();
    else if (key === "delete") removeSelected();
    else if (key === "t") startTap();
    else if (key === "+") zoom(1 / 1.5);
    else if (key === "-") zoom(1.5);
    else return;
    event.preventDefault();
  }

  function onKeyUp(event: KeyboardEvent) {
    if (tap && event.code === "Space") tapRelease();
  }

  // --- timeline ----------------------------------------------------------------

  function zoom(factor: number, anchor = 0.5) {
    view = zoomView(view, factor, anchor, duration);
  }

  function point(event: MouseEvent): { x: number; y: number } {
    const rect = canvas!.getBoundingClientRect();
    return { x: event.clientX - rect.left, y: event.clientY - rect.top };
  }

  function onPointerDown(event: PointerEvent) {
    if (event.button !== 0 || !canvas) return;
    const { x, y } = point(event);
    try {
      canvas.setPointerCapture(event.pointerId);
    } catch {
      // il puntatore è già stato rilasciato: il gesto vale finché resta sulla timeline
    }
    const hit = tap ? null : hitTest(lines, selected, view, x, y);
    if (!hit) {
      drag = { kind: "scrub" };
      seek(xToTime(view, x));
    } else if (hit.kind === "line") {
      select(hit.line);
      // Un bordo che combacia con quello della riga accanto è il confine tra le due: si trascinano insieme.
      const line = lines[hit.line];
      const other = hit.part === "start" ? lines[hit.line - 1]?.end : hit.part === "end" ? lines[hit.line + 1]?.start : undefined;
      const own = hit.part === "start" ? line.start : line.end;
      const linked = !event.altKey && other !== undefined && Math.abs(other - own) < LINK_S;
      drag = { kind: "line", part: hit.part, index: hit.line, linked, origin: lines, grab: xToTime(view, x) - line.start, x, moved: false };
    } else {
      const words = wordsOf(lines[hit.line])!;
      const own = words[hit.word][hit.edge];
      const other = hit.edge === "start" ? words[hit.word - 1]?.end : words[hit.word + 1]?.start;
      const linked = !event.altKey && other !== undefined && Math.abs(other - own) < LINK_S;
      drag = { kind: "word", index: hit.line, word: hit.word, edge: hit.edge, linked, origin: lines, x, moved: false };
    }
  }

  function onPointerMove(event: PointerEvent) {
    if (!canvas) return;
    const { x, y } = point(event);
    if (!drag) {
      canvas.style.cursor = cursorFor(tap ? null : hitTest(lines, selected, view, x, y));
      return;
    }
    const t = xToTime(view, x);
    if (drag.kind === "scrub") return seek(t);
    if (!drag.moved) {
      if (Math.abs(x - drag.x) < 3) return;   // un clic con la mano poco ferma non è un trascinamento
      drag.moved = true;
      canvas.style.cursor = drag.kind === "line" && drag.part === "body" ? "grabbing" : "ew-resize";
    }
    const reach = (SNAP_PX / view.width) * view.span;
    const near = (time: number, edge: "start" | "end") => (snap ? snapTime(time, notes, edge, reach) : time);
    if (drag.kind === "word") {
      lines = moveWordEdge(drag.origin, drag.index, drag.word, drag.edge, near(t, drag.edge), drag.linked);
    } else if (drag.part === "body") {
      lines = moveLine(drag.origin, drag.index, near(t - drag.grab, "start"), duration);
    } else if (drag.part === "start") {
      lines = resizeStart(drag.origin, drag.index, near(t, "start"), duration, drag.linked);
    } else {
      lines = resizeEnd(drag.origin, drag.index, near(t, "end"), duration, drag.linked);
    }
  }

  function onPointerUp() {
    const done = drag;
    drag = null;
    if (!done || done.kind === "scrub") return;
    if (!done.moved) {
      if (done.kind === "line") seek(lines[done.index].start);   // un clic sulla riga: si va al suo inizio
    } else if (lines !== done.origin) {
      history.record(done.origin);
      notice = "";
      syncHistory();
    }
  }

  function onDoubleClick(event: MouseEvent) {
    const { x, y } = point(event);
    const hit = tap ? null : hitTest(lines, selected, view, x, y);
    if (hit?.kind === "line") playLine(hit.line);
  }

  function onWheel(event: WheelEvent) {
    event.preventDefault();
    const { x } = point(event);
    if (event.ctrlKey) zoom(event.deltaY > 0 ? 1.2 : 1 / 1.2, x / view.width);
    else view = clampView({ ...view, start: view.start + ((event.deltaY || event.deltaX) / 600) * view.span }, duration);
  }

  // I gesti sulla timeline si ascoltano a mano: la rotella deve poter fermare lo scorrimento della pagina.
  $effect(() => {
    const element = canvas;
    if (!element) return;
    element.addEventListener("pointerdown", onPointerDown);
    element.addEventListener("pointermove", onPointerMove);
    element.addEventListener("pointerup", onPointerUp);
    element.addEventListener("pointercancel", onPointerUp);
    element.addEventListener("dblclick", onDoubleClick);
    element.addEventListener("wheel", onWheel, { passive: false });
    return () => {
      element.removeEventListener("pointerdown", onPointerDown);
      element.removeEventListener("pointermove", onPointerMove);
      element.removeEventListener("pointerup", onPointerUp);
      element.removeEventListener("pointercancel", onPointerUp);
      element.removeEventListener("dblclick", onDoubleClick);
      element.removeEventListener("wheel", onWheel);
    };
  });

  // Un pulsante cliccato col mouse non si tiene la tastiera: Spazio deve tornare a riprodurre.
  $effect(() => {
    const element = root;
    if (!element) return;
    const release = (event: MouseEvent) => {
      if (event.detail > 0) (event.target as HTMLElement).closest("button")?.blur();
    };
    element.addEventListener("click", release);
    return () => element.removeEventListener("click", release);
  });

  /** I caratteri [da, a) della parola numero `index` nel testo. */
  function tokenSpan(text: string, index: number): [number, number] {
    let from = 0;
    let to = 0;
    tokens(text).slice(0, index + 1).forEach((token) => {
      from = text.indexOf(token, to);
      to = from + token.length;
    });
    return [from, to];
  }

  /** La riga come la vedrà chi gioca; battendo il tempo, quella che aspetta il tocco. */
  function previewAt(now: number): Preview | null {
    if (tap) {
      const line = lines[tap.line];
      if (!line) return null;
      const [from, to] = tapUnit === "word" ? tokenSpan(line.text, tap.word) : [0, line.text.length];
      return { before: line.text.slice(0, from), word: line.text.slice(from, to), after: line.text.slice(to), next: lines[tap.line + 1]?.text ?? "" };
    }
    const { current: index, next } = lineAt(lines, now);
    if (index < 0) return next >= 0 && lines[next].start - now < 5 ? { before: "", word: "", after: "", next: lines[next].text } : null;
    const line = lines[index];
    const [from, to] = wordSpan({ ...line, words: wordsOf(line) }, now) ?? [0, 0];
    return { before: line.text.slice(0, from), word: line.text.slice(from, to), after: line.text.slice(to), next: next >= 0 ? lines[next].text : "" };
  }

  function loop() {
    frame = requestAnimationFrame(loop);
    if (!active || !canvas || !audio) return;
    const width = canvas.clientWidth;
    if (width === 0) return;
    const now = heard();
    if (stopAt !== null && !audio.paused && now >= stopAt) {
      audio.pause();
      stopAt = null;
    }
    view = { ...view, width };
    if (!audio.paused && !drag) view = followView(view, now, duration);

    const text = formatClock(now);
    if (text !== clock) clock = text;
    const at = lineIndexAt(lines, now);
    if (at !== playingLine) playingLine = at;
    const shown = previewAt(now);
    if (shown?.before !== preview?.before || shown?.word !== preview?.word || shown?.after !== preview?.after || shown?.next !== preview?.next) {
      preview = shown;
    }

    const dpr = window.devicePixelRatio || 1;
    if (canvas.width !== Math.round(width * dpr) || canvas.height !== Math.round(TIMELINE_HEIGHT * dpr)) {
      canvas.width = Math.round(width * dpr);
      canvas.height = Math.round(TIMELINE_HEIGHT * dpr);
    }
    const g = canvas.getContext("2d")!;
    g.setTransform(dpr, 0, 0, dpr, 0, 0);
    drawTimeline(g, { view, lines, selected, playing: at, tapping: tap ? tap.line : -1, notes, range, peaks, rate: peakRate, now });
  }
</script>

<svelte:window onkeydown={onKeyDown} onkeyup={onKeyUp} onblur={tapRelease} />

<div class="editor" bind:this={root}>
  {#if broken}
    <div class="banner">Non riesco a leggere il testo di questo brano: {broken}</div>
  {:else}
    <div class="row bar">
      <button class="primary play" onclick={togglePlay} title="Spazio">{playing ? "Pausa" : "Riproduci"}</button>
      <button onclick={() => seek(heard() - SEEK_S)} title="Indietro di 2 secondi (←)">−2 s</button>
      <button onclick={() => seek(heard() + SEEK_S)} title="Avanti di 2 secondi (→)">+2 s</button>
      <span class="clock" title="Posizione nel brano">{clock}</span>
      <label>
        Ascolto
        <select value={track} onchange={(e) => { switchTrack(e.currentTarget.value as AudioTrack); e.currentTarget.blur(); }}>
          {#each TRACKS as option (option.value)}<option value={option.value}>{option.label}</option>{/each}
        </select>
      </label>
      <label>
        Velocità
        <select value={rate} onchange={(e) => { rate = Number(e.currentTarget.value); e.currentTarget.blur(); }}>
          {#each RATES as option (option)}<option value={option}>{option}×</option>{/each}
        </select>
      </label>
      <label class="check" title="Gli istanti segnati o trascinati vicino all'inizio o alla fine di una nota cantata ci vanno sopra">
        <input type="checkbox" bind:checked={snap} onchange={(e) => e.currentTarget.blur()} /> Aggancia alle note
      </label>
      <span class="spacer"></span>
      <button onclick={() => zoom(1 / 1.5)} title="Ingrandisci (+, oppure Ctrl + rotella)">+</button>
      <button onclick={() => zoom(1.5)} title="Rimpicciolisci (−, oppure Ctrl + rotella)">−</button>
    </div>

    <div class="preview" class:tapping={tap !== null}>
      <div class="shown">
        {#if preview && (preview.before || preview.word || preview.after)}
          <span class="sung">{preview.before}</span><span class="word">{preview.word}</span><span>{preview.after}</span>
        {:else}
          <span class="idle">♪</span>
        {/if}
      </div>
      <div class="upcoming">{preview?.next ?? ""}</div>
    </div>

    <canvas bind:this={canvas} style:height="{TIMELINE_HEIGHT}px"></canvas>

    {#if tap}
      <div class="row tools tapbar">
        <button
          class="primary beat" class:down={tap.downAt !== null}
          onpointerdown={tapPress} onpointerup={tapRelease} onpointerleave={tapRelease}
        >Batti</button>
        <span class="how">
          Tieni premuto <kbd>Spazio</kbd> mentre senti cantare la {tapUnit === "word" ? "parola" : "riga"} evidenziata e rilascia quando finisce.
          Un tocco breve segna solo l'inizio. <kbd>←</kbd> <kbd>→</kbd> saltano di 2 secondi.
        </span>
        <span class="spacer"></span>
        <label>
          Batto
          <select bind:value={tapUnit} onchange={(e) => e.currentTarget.blur()}>
            <option value="line">riga per riga</option>
            <option value="word">parola per parola</option>
          </select>
        </label>
        <button onclick={tapStepBack} title="Torna alla riga precedente e la riascolta (Backspace)">Indietro</button>
        <button onclick={stopTap} title="Esc">Fine</button>
      </div>
    {:else}
      <div class="row tools">
        {#if current}
          <strong class="which">Riga {selected + 1}</strong>
          <button onclick={() => playLine(selected)} title="Ascolta solo questa riga (R, o doppio clic sulla riga)">Ascolta</button>
          <label>
            Inizio
            <input class="time" type="text" value={formatClock(current.start)} onchange={(e) => editTime(e, "start")} />
          </label>
          <button onclick={startHere} title="La riga comincia dove sta il cursore dell'audio (I)">Qui</button>
          <label>
            Fine
            <input class="time" type="text" value={formatClock(current.end)} onchange={(e) => editTime(e, "end")} />
          </label>
          <button onclick={endHere} title="La riga finisce dove sta il cursore dell'audio (O)">Qui</button>
          <button onclick={() => nudge(-NUDGE_S)} title="Anticipa la riga di 5 centesimi (,)">◀</button>
          <button onclick={() => nudge(NUDGE_S)} title="Ritarda la riga di 5 centesimi (.)">▶</button>
          <button onclick={splitSelected} title="Divide la riga dove sta il cursore del testo (Invio mentre scrivi)">Dividi</button>
          <button onclick={() => mergeAt(selected)} disabled={selected + 1 >= lines.length} title="Unisce questa riga alla successiva (Canc in fondo al testo)">Unisci</button>
          <button class="danger" onclick={removeSelected} title="Elimina la riga (Canc)">Elimina</button>
        {/if}
        <button onclick={addLine} title="Aggiunge una riga dove sta il cursore dell'audio; se lì c'è già una riga, dopo quella selezionata (N)">+ Riga</button>
      </div>

      <div class="row tools">
        <button class="primary" onclick={startTap} disabled={lines.length === 0} title="Sincronizza ascoltando: parte dalla riga selezionata (T)">Batti il tempo</button>
        <button onclick={undo} disabled={!canUndo} title="Ctrl+Z">Annulla</button>
        <button onclick={redo} disabled={!canRedo} title="Ctrl+Y">Ripeti</button>
        <button onclick={openPaste} title="Incolla o riscrivi tutto il testo, anche in formato LRC">Incolla testo…</button>
        <button onclick={exportLrc} disabled={lines.length === 0} title="Scarica il testo con i tempi in formato LRC">Esporta LRC</button>
        <span class="group">
          Sposta tutto
          <button onclick={() => shiftEverything(-SHIFT_S)} disabled={lines.length === 0} title="Tutto il testo arriva un decimo di secondo prima">−0,1 s</button>
          <button onclick={() => shiftEverything(SHIFT_S)} disabled={lines.length === 0} title="Tutto il testo arriva un decimo di secondo dopo">+0,1 s</button>
        </span>
        <span class="spacer"></span>
        {#if error}<span class="error">{error}</span>{:else if notice}<span class="notice">{notice}</span>{:else if dirty}<span class="unsaved">Modifiche non salvate</span>{/if}
        <button class="primary" onclick={save} disabled={!dirty || saving} title="Ctrl+S">{saving ? "Salvo…" : "Salva testo"}</button>
      </div>
    {/if}

    <details class="help">
      <summary>Come si usa e scorciatoie</summary>
      <div class="columns">
        <p>
          <strong>Sulla timeline</strong> in alto c'è il volume della voce con le note cantate, sotto le righe e le parole.
          Trascina una riga per spostarla, i suoi bordi per allungarla o accorciarla: il confine tra due righe attaccate
          si sposta per entrambe, e una riga spinta contro la vicina la accorcia. Con una riga selezionata si trascinano
          anche i confini tra le parole. <kbd>Alt</kbd> muove un bordo solo. Un clic altrove sposta il cursore dell'audio,
          la rotella scorre, <kbd>Ctrl</kbd> + rotella ingrandisce.
        </p>
        <p>
          <strong>Nel testo</strong> <kbd>Invio</kbd> divide la riga dove sta il cursore, <kbd>Backspace</kbd> a inizio riga la unisce
          alla precedente, <kbd>↑</kbd> <kbd>↓</kbd> cambiano riga, <kbd>Esc</kbd> esce dal campo.
        </p>
        <p>
          <strong>Fuori dal testo</strong> <kbd>Spazio</kbd> riproduce o ferma, <kbd>←</kbd> <kbd>→</kbd> saltano di 2 secondi
          (con <kbd>Maiusc</kbd> mezzo secondo), <kbd>↑</kbd> <kbd>↓</kbd> scelgono la riga, <kbd>I</kbd> e <kbd>O</kbd> ne segnano
          inizio e fine dove sta l'audio, <kbd>,</kbd> <kbd>.</kbd> la spostano di 5 centesimi, <kbd>R</kbd> la riascolta,
          <kbd>Invio</kbd> ne modifica il testo, <kbd>N</kbd> aggiunge una riga, <kbd>Canc</kbd> la elimina, <kbd>T</kbd> batte il tempo.
        </p>
        <p>
          <strong>Ovunque</strong> <kbd>Ctrl</kbd>+<kbd>Spazio</kbd> riproduce o ferma, <kbd>Ctrl</kbd>+<kbd>Z</kbd> annulla,
          <kbd>Ctrl</kbd>+<kbd>Y</kbd> ripete, <kbd>Ctrl</kbd>+<kbd>S</kbd> salva.
        </p>
      </div>
    </details>

    {#if !loaded}
      <p class="muted empty">Carico il testo…</p>
    {:else if lines.length === 0}
      <div class="empty">
        <p>Questo brano non ha testo: si gioca comunque, seguendo solo le barre.</p>
        <p class="muted">
          Per aggiungerlo incolla le parole (anche con i tempi, in formato LRC) e poi sincronizzale con «Batti il tempo»,
          oppure aggiungi le righe una alla volta mentre ascolti.
        </p>
        <div class="row">
          <button class="primary" onclick={openPaste}>Incolla testo…</button>
          <button onclick={addLine}>+ Riga</button>
        </div>
      </div>
    {:else}
      <div class="lines" bind:this={list}>
        {#each lines as line, i (i)}
          <div class="line" class:selected={i === selected} class:playing={i === playingLine} class:tapping={tap?.line === i}>
            <button class="number" onclick={() => { select(i); seek(line.start); }} title="Seleziona la riga e porta l'audio al suo inizio">
              {i + 1}
            </button>
            <span class="times">{formatClock(line.start)} – {formatClock(line.end)}</span>
            <input
              class="text" type="text" value={line.text} readonly={tap !== null} spellcheck="false"
              aria-label="Testo della riga {i + 1}" placeholder="Riga vuota: scrivi il testo"
              oninput={(e) => onText(i, e.currentTarget.value)}
              onfocus={() => { if (!tap) selected = i; }}
              onkeydown={(e) => onTextKey(e, i)}
            />
            {#if issues[i]}
              <span class="flag warn" title={issues[i]}>⚠</span>
            {:else if wordsOf(line)}
              <span class="flag" title="Questa riga ha i tempi parola per parola">parole</span>
            {:else}
              <span class="flag"></span>
            {/if}
          </div>
        {/each}
      </div>
    {/if}
  {/if}

  <audio
    bind:this={audio} src={audioUrl(song.id, track)} preload="auto"
    onplay={() => (playing = true)} onpause={() => (playing = false)}
    onended={() => { playing = false; stopTap(); }}
    onloadedmetadata={() => (audioDuration = Number.isFinite(audio?.duration) ? audio!.duration : 0)}
    onerror={onAudioError}
  ></audio>

  <dialog bind:this={dialog} onclose={() => (pasteOpen = false)}>
    <h2>Incolla il testo</h2>
    <p class="muted">
      Una riga per ogni verso. Va bene anche un testo con i tempi in formato LRC (<code>[mm:ss.cc]</code> davanti a ogni riga).
    </p>
    <textarea bind:value={pasteText} rows="16" spellcheck="false"></textarea>
    <p class="muted hint">{pasteHint}</p>
    <div class="row">
      <button class="primary" onclick={applyPaste} disabled={paste.count === 0}>Usa questo testo</button>
      <button onclick={() => dialog?.close()}>Annulla</button>
    </div>
  </dialog>
</div>

<style>
  .editor { display: flex; flex-direction: column; flex: 1; min-height: 0; }
  .bar { margin-bottom: 0.6rem; }
  .bar label, .tools label { display: flex; align-items: center; gap: 0.4rem; color: var(--muted); }
  .check input { accent-color: var(--accent); }
  .spacer { flex: 1; }
  .play { min-width: 6.5rem; }
  .clock { font-variant-numeric: tabular-nums; min-width: 4.6rem; font-size: 1.05rem; }
  select { padding: 0.35rem 0.5rem; }

  .preview { text-align: center; margin-bottom: 0.5rem; min-height: 3.6rem; }
  .shown { font-size: 1.35rem; font-weight: 600; min-height: 1.9rem; white-space: pre-wrap; }
  .sung { color: var(--accent); }
  .word { color: var(--warn); }
  .idle { color: var(--dim); }
  .upcoming { color: var(--dim); min-height: 1.3rem; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .preview.tapping .shown { font-size: 1.6rem; }

  canvas { width: 100%; display: block; border: 1px solid var(--line); border-radius: 10px; cursor: crosshair; touch-action: none; flex: none; }

  .tools { margin-top: 0.6rem; }
  .tools button { padding: 0.35rem 0.7rem; }
  .which { min-width: 4.2rem; }
  .time { width: 5.4rem; padding: 0.3rem 0.5rem; font-variant-numeric: tabular-nums; }
  .group { display: flex; align-items: center; gap: 0.4rem; color: var(--muted); margin-left: 0.4rem; }
  .notice { color: var(--good); }
  .unsaved { color: var(--warn); }
  .tapbar { background: var(--panel); border: 1px solid var(--warn); border-radius: 10px; padding: 0.6rem 0.75rem; }
  .tapbar .how { color: var(--muted); max-width: 46rem; }
  .beat { min-width: 6.5rem; padding: 0.7rem 1rem; touch-action: none; user-select: none; }
  .beat.down { background: var(--warn); border-color: var(--warn); }
  kbd {
    font: inherit; font-size: 0.85em; background: var(--panel-2); border: 1px solid var(--line);
    border-radius: 5px; padding: 0.05rem 0.35rem; color: var(--text);
  }

  .help { margin-top: 0.6rem; color: var(--muted); font-size: 0.9rem; }
  .help summary { cursor: pointer; width: fit-content; }
  .columns { display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 0 1.5rem; }
  .columns p { margin: 0.5rem 0 0; line-height: 1.6; }
  .columns strong { color: var(--text); }

  .lines { flex: 1; min-height: 180px; overflow-y: auto; margin-top: 0.6rem; border: 1px solid var(--line); border-radius: 10px; background: var(--panel); }
  .line { display: grid; grid-template-columns: 2.6rem 9.2rem 1fr 3.6rem; align-items: center; gap: 0.5rem; padding: 0.15rem 0.5rem; border-left: 3px solid transparent; }
  .line.playing { background: rgba(91, 140, 255, 0.1); }
  .line.selected { border-left-color: var(--accent); background: rgba(91, 140, 255, 0.18); }
  .line.tapping { border-left-color: var(--warn); background: rgba(255, 209, 102, 0.12); }
  .number { padding: 0.15rem 0; background: none; border-color: transparent; color: var(--muted); font-variant-numeric: tabular-nums; }
  .times { color: var(--dim); font-variant-numeric: tabular-nums; font-size: 0.85rem; white-space: nowrap; }
  .line.selected .times, .line.playing .times { color: var(--muted); }
  .text { width: 100%; background: transparent; border-color: transparent; padding: 0.3rem 0.5rem; }
  .text:hover { border-color: var(--line); }
  .text:focus { background: var(--bg); }
  .flag { color: var(--dim); font-size: 0.75rem; text-align: right; }
  .flag.warn { color: var(--warn); font-size: 1rem; cursor: help; }
  .empty { margin-top: 1rem; }

  dialog { width: min(720px, 92vw); background: var(--panel); color: var(--text); border: 1px solid var(--line); border-radius: 12px; padding: 1.1rem; }
  dialog::backdrop { background: rgba(8, 10, 16, 0.7); }
  dialog textarea { width: 100%; resize: vertical; font-family: inherit; line-height: 1.5; }
  .hint { min-height: 1.3rem; }
</style>
