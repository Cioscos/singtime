<script lang="ts">
  // Vista di sviluppo: sovrappone la curva di altezza grezza e le barre generate,
  // con l'audio della voce isolata, per tarare l'algoritmo guardando e ascoltando.
  import { onMount, tick } from "svelte";
  import {
    applyNotes, audioUrl, getNoteParams, getNotes, getPitch, getSong, getSwiftF0Notes,
    previewNotes, putNoteParams,
  } from "../lib/api";
  import { midiToY, pitchRange, visibleSlice, type PitchRange } from "../game/layout";
  import { formatDuration } from "../lib/status";
  import type { Note, NoteParams, PitchData, Song } from "../lib/types";

  let { id }: { id: string } = $props();

  const SLIDERS: { key: keyof NoteParams; label: string; min: number; max: number; step: number; unit: string }[] = [
    { key: "min_note_s", label: "Durata minima di una nota", min: 0.04, max: 0.4, step: 0.01, unit: "s" },
    { key: "max_gap_s", label: "Pausa ricucita dentro una nota", min: 0, max: 0.3, step: 0.01, unit: "s" },
    { key: "vibrato_window_s", label: "Finestra che appiattisce il vibrato", min: 0.05, max: 0.5, step: 0.01, unit: "s" },
    { key: "split_semitones", label: "Scarto che divide due note", min: 0.3, max: 2, step: 0.05, unit: "semitoni" },
    { key: "settle_s", label: "Quanto deve durare lo scarto", min: 0.02, max: 0.2, step: 0.01, unit: "s" },
    { key: "merge_semitones", label: "Note vicine da unire", min: 0, max: 1.5, step: 0.05, unit: "semitoni" },
  ];

  let song = $state<Song | null>(null);
  // Vettori grandi: senza proxy profondi, altrimenti il disegno rallenta.
  let pitch = $state.raw<PitchData | null>(null);
  let notes = $state.raw<Note[]>([]);
  let compare = $state.raw<Note[] | null>(null);
  let showCompare = $state(false);
  let params = $state<NoteParams | null>(null);
  let defaults = $state.raw<NoteParams | null>(null);
  let which = $state<"vocals" | "instrumental">("vocals");
  let playing = $state(false);
  let message = $state("");
  let error = $state("");
  let unsaved = $state(false);

  let viewStart = $state(0);
  let viewSpan = $state(12);
  let curveRange = $state.raw<PitchRange | null>(null);

  let canvas = $state<HTMLCanvasElement>();
  let audio = $state<HTMLAudioElement>();
  let frame = 0;
  let previewTimer: ReturnType<typeof setTimeout> | undefined;
  let previewSeq = 0;

  const duration = $derived(song?.duration_s ?? (pitch?.times.at(-1) ?? 0));
  const range = $derived.by(() => {
    const base = pitchRange(notes);
    if (!curveRange) return base;
    return { min: Math.min(base.min, curveRange.min), max: Math.max(base.max, curveRange.max) };
  });
  const stats = $derived.by(() => {
    if (notes.length === 0) return null;
    const durations = notes.map((n) => n.duration).sort((a, b) => a - b);
    return { count: notes.length, shortest: durations[0], median: durations[Math.floor(durations.length / 2)] };
  });

  onMount(() => {
    load();
    frame = requestAnimationFrame(loop);
    return () => {
      cancelAnimationFrame(frame);
      clearTimeout(previewTimer);
    };
  });

  async function load() {
    try {
      [song, pitch, notes, defaults] = await Promise.all([getSong(id), getPitch(id), getNotes(id), getNoteParams()]);
      params = { ...defaults! };
      if (notes.length > 0) viewStart = Math.max(0, notes[0].start - 1);  // si apre dove comincia il canto
      const voiced = pitch!.midi.filter((m): m is number => m !== null).sort((a, b) => a - b);
      if (voiced.length > 0) {
        curveRange = {
          min: voiced[Math.floor(voiced.length * 0.02)] - 2,
          max: voiced[Math.floor(voiced.length * 0.98)] + 2,
        };
      }
      getSwiftF0Notes(id).then((result) => (compare = result)).catch(() => (compare = null));
    } catch (e) {
      error = (e as Error).message;
    }
  }

  // --- disegno ---------------------------------------------------------------

  function firstIndexAtOrAfter(times: number[], t: number): number {
    let low = 0;
    let high = times.length;
    while (low < high) {
      const middle = (low + high) >> 1;
      if (times[middle] < t) low = middle + 1;
      else high = middle;
    }
    return low;
  }

  function loop() {
    draw();
    frame = requestAnimationFrame(loop);
  }

  function draw() {
    if (!canvas) return;
    const dpr = window.devicePixelRatio || 1;
    const width = canvas.clientWidth;
    const height = canvas.clientHeight;
    if (canvas.width !== Math.round(width * dpr) || canvas.height !== Math.round(height * dpr)) {
      canvas.width = Math.round(width * dpr);
      canvas.height = Math.round(height * dpr);
    }
    const g = canvas.getContext("2d")!;
    g.setTransform(dpr, 0, 0, dpr, 0, 0);
    g.fillStyle = "#12141c";
    g.fillRect(0, 0, width, height);

    const now = audio?.currentTime ?? 0;
    if (audio && !audio.paused && (now > viewStart + viewSpan * 0.85 || now < viewStart)) {
      viewStart = Math.max(0, now - viewSpan * 0.15);  // segue la riproduzione
    }
    const top = 14;
    const bottom = height - 26;
    const x = (t: number) => ((t - viewStart) / viewSpan) * width;
    const y = (midi: number) => midiToY(midi, range, top, bottom);
    const semitone = (bottom - top) / (range.max - range.min);
    const viewEnd = viewStart + viewSpan;

    // righe dei semitoni, più marcate sui Do
    g.font = "10px system-ui, sans-serif";
    for (let midi = Math.ceil(range.min); midi <= Math.floor(range.max); midi++) {
      const isC = midi % 12 === 0;
      g.strokeStyle = isC ? "#2f3548" : "#1b1f2c";
      g.beginPath();
      g.moveTo(0, y(midi));
      g.lineTo(width, y(midi));
      g.stroke();
      if (isC) {
        g.fillStyle = "#55607a";
        g.fillText(`Do${midi / 12 - 1}`, 4, y(midi) - 3);
      }
    }
    // asse del tempo
    const tick = viewSpan > 40 ? 10 : viewSpan > 15 ? 5 : 1;
    g.fillStyle = "#55607a";
    for (let t = Math.ceil(viewStart / tick) * tick; t <= viewEnd; t += tick) {
      g.fillRect(x(t), bottom + 4, 1, 5);
      g.fillText(formatDuration(t), x(t) + 3, height - 6);
    }

    // barre di confronto (swift-f0), dietro
    if (showCompare && compare) {
      const [from, to] = visibleSlice(compare, viewStart, viewEnd);
      g.strokeStyle = "#ff9f43";
      g.lineWidth = 2;
      for (let i = from; i < to; i++) {
        const note = compare[i];
        g.strokeRect(x(note.start), y(note.pitch) - semitone * 0.6, Math.max(1, x(note.start + note.duration) - x(note.start)), semitone * 1.2);
      }
      g.lineWidth = 1;
    }

    // le nostre barre
    const [from, to] = visibleSlice(notes, viewStart, viewEnd);
    const barHeight = Math.max(4, semitone * 0.8);
    for (let i = from; i < to; i++) {
      const note = notes[i];
      g.fillStyle = "rgba(91, 140, 255, 0.75)";
      g.fillRect(x(note.start), y(note.pitch) - barHeight / 2, Math.max(1, x(note.start + note.duration) - x(note.start) - 1), barHeight);
    }

    // curva grezza, sopra a tutto
    if (pitch) {
      const { times, midi } = pitch;
      g.fillStyle = "#e8ebf4";
      const end = firstIndexAtOrAfter(times, viewEnd);
      for (let i = firstIndexAtOrAfter(times, viewStart); i < end; i++) {
        const value = midi[i];
        if (value !== null) g.fillRect(x(times[i]) - 0.75, y(value) - 0.75, 1.5, 1.5);
      }
    }

    // cursore della riproduzione
    g.fillStyle = "#ffd166";
    g.fillRect(x(now) - 1, top - 6, 2, bottom - top + 12);
  }

  // --- interazione -------------------------------------------------------------

  function clampView() {
    viewSpan = Math.min(Math.max(viewSpan, 2), Math.max(duration, 2));
    viewStart = Math.min(Math.max(viewStart, 0), Math.max(0, duration - viewSpan));
  }

  function zoom(factor: number, anchor = 0.5) {
    const pivot = viewStart + viewSpan * anchor;
    viewSpan *= factor;
    viewStart = pivot - viewSpan * anchor;
    clampView();
  }

  function onWheel(event: WheelEvent) {
    event.preventDefault();
    const rect = canvas!.getBoundingClientRect();
    if (event.ctrlKey) {
      zoom(event.deltaY > 0 ? 1.2 : 1 / 1.2, (event.clientX - rect.left) / rect.width);
    } else {
      viewStart += ((event.deltaY || event.deltaX) / 600) * viewSpan;
      clampView();
    }
  }

  // La rotella deve poter bloccare lo scorrimento della pagina: serve un ascoltatore non passivo.
  $effect(() => {
    const element = canvas;
    if (!element) return;
    element.addEventListener("wheel", onWheel, { passive: false });
    return () => element.removeEventListener("wheel", onWheel);
  });

  function seek(event: MouseEvent) {
    if (!audio) return;
    const rect = canvas!.getBoundingClientRect();
    audio.currentTime = viewStart + ((event.clientX - rect.left) / rect.width) * viewSpan;
  }

  function togglePlay() {
    if (!audio) return;
    if (audio.paused) audio.play();
    else audio.pause();
  }

  async function switchTrack(next: "vocals" | "instrumental") {
    if (!audio || next === which) return;
    const time = audio.currentTime;
    const wasPlaying = !audio.paused;
    which = next;
    await tick();
    audio.currentTime = time;
    if (wasPlaying) audio.play();
  }

  function onKey(event: KeyboardEvent) {
    if (event.code === "Space" && !(event.target instanceof HTMLInputElement)) {
      event.preventDefault();
      togglePlay();
    }
  }

  // --- soglie --------------------------------------------------------------------

  function schedulePreview() {
    clearTimeout(previewTimer);
    previewTimer = setTimeout(async () => {
      if (!params) return;
      const seq = ++previewSeq;
      try {
        const result = await previewNotes(id, $state.snapshot(params));
        if (seq === previewSeq) {
          notes = result;
          unsaved = true;
          error = "";
        }
      } catch (e) {
        error = (e as Error).message;
      }
    }, 60);
  }

  async function applyToSong() {
    if (!params) return;
    try {
      notes = await applyNotes(id, $state.snapshot(params));
      unsaved = false;
      error = "";
      message = `Tracciato di questo brano salvato (${notes.length} note).`;
    } catch (e) {
      error = (e as Error).message;
    }
  }

  async function saveDefaults() {
    if (!params) return;
    try {
      defaults = await putNoteParams($state.snapshot(params));
      error = "";
      message = "Predefiniti salvati: varranno per i prossimi brani elaborati.";
    } catch (e) {
      error = (e as Error).message;
    }
  }

  function resetParams() {
    if (!defaults) return;
    params = { ...defaults };
    schedulePreview();
  }
</script>

<svelte:window onkeydown={onKey} />

<main class="page wide">
  <div class="topbar">
    <div>
      <a href="#/library">← Libreria</a>
      <h1>Verifica: {song?.title ?? "…"}</h1>
      <div class="muted">
        {song ? [song.artist, `separatore ${song.separator_model}`, `altezza ${song.pitch_tracker}`].filter(Boolean).join(" · ") : ""}
      </div>
    </div>
    {#if stats}
      <div class="stats">
        <strong>{stats.count}</strong> note · più corta <strong>{stats.shortest.toFixed(2)} s</strong> ·
        mediana <strong>{stats.median.toFixed(2)} s</strong>
        {#if unsaved}<span class="unsaved">anteprima non salvata</span>{/if}
      </div>
    {/if}
  </div>

  {#if error}<div class="banner">{error}</div>{/if}

  <div class="row controls">
    <button class="primary" onclick={togglePlay}>{playing ? "Pausa" : "Riproduci"}</button>
    <label><input type="radio" checked={which === "vocals"} onchange={() => switchTrack("vocals")} /> voce isolata</label>
    <label><input type="radio" checked={which === "instrumental"} onchange={() => switchTrack("instrumental")} /> base</label>
    <span class="spacer"></span>
    <label class:disabled={!compare}>
      <input type="checkbox" bind:checked={showCompare} disabled={!compare} />
      {compare ? "Mostra confronto swift-f0" : "Confronto swift-f0 non disponibile per questo brano"}
    </label>
    <button onclick={() => zoom(1 / 1.5)} title="Ingrandisci">+</button>
    <button onclick={() => zoom(1.5)} title="Rimpicciolisci">−</button>
  </div>

  <canvas bind:this={canvas} onclick={seek}></canvas>
  <p class="muted legend">
    <span class="dot curve"></span> voce rilevata
    <span class="dot bar"></span> barre generate
    {#if showCompare}<span class="dot cmp"></span> barre di swift-f0{/if}
    · rotella: scorri · Ctrl + rotella: zoom · clic: salta a quel punto · Spazio: riproduci/pausa
  </p>

  <audio bind:this={audio} src={audioUrl(id, which)} preload="auto"
         onplay={() => (playing = true)} onpause={() => (playing = false)}></audio>

  {#if params}
    <section class="panel">
      <h2>Soglie dell'algoritmo</h2>
      <div class="sliders">
        {#each SLIDERS as slider (slider.key)}
          <label class="slider">
            <span>{slider.label}</span>
            <input type="range" min={slider.min} max={slider.max} step={slider.step}
                   bind:value={params[slider.key]} oninput={schedulePreview} />
            <output>{params[slider.key].toFixed(2)} {slider.unit}</output>
          </label>
        {/each}
      </div>
      <div class="row">
        <button class="primary" onclick={applyToSong}>Applica a questo brano</button>
        <button onclick={saveDefaults}>Salva come predefiniti</button>
        <button onclick={resetParams}>Torna ai predefiniti</button>
        {#if message}<span class="muted">{message}</span>{/if}
      </div>
    </section>
  {/if}
</main>

<style>
  .wide { max-width: 1400px; }
  .stats { text-align: right; color: var(--muted); }
  .stats strong { color: var(--text); }
  .unsaved { display: block; color: var(--warn); font-size: 0.9rem; }
  .controls { margin-bottom: 0.6rem; }
  .spacer { flex: 1; }
  .disabled { color: var(--dim); }
  canvas { width: 100%; height: 440px; display: block; border: 1px solid var(--line); border-radius: 10px; cursor: crosshair; }
  .legend { font-size: 0.85rem; margin: 0.4rem 0 1rem; }
  .dot { display: inline-block; width: 10px; height: 10px; border-radius: 2px; margin: 0 0.25rem 0 0.6rem; }
  .dot.curve { background: #e8ebf4; }
  .dot.bar { background: #5b8cff; }
  .dot.cmp { border: 2px solid #ff9f43; }
  .sliders { display: grid; grid-template-columns: repeat(auto-fit, minmax(380px, 1fr)); gap: 0.5rem 2rem; margin-bottom: 1rem; }
  .slider { display: grid; grid-template-columns: 1fr 160px 110px; align-items: center; gap: 0.75rem; }
  .slider output { color: var(--muted); font-variant-numeric: tabular-nums; }
  h1 { margin-top: 0.3rem; }
</style>
