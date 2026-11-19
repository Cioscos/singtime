<script lang="ts">
  import { onMount } from "svelte";
  import { SongPlayer } from "../game/audio";
  import { pitchRange, targetNote, type PitchRange } from "../game/layout";
  import { lineAt, sungFraction } from "../game/lyrics-progress";
  import { Mic, MicDeniedError, type PitchReading } from "../game/mic";
  import { foldToOctave } from "../game/pitch-math";
  import { drawFrame } from "../game/render";
  import { ScoreKeeper } from "../game/scoring";
  import { getLyrics, getNotes, getSettings, getSong, putSettings } from "../lib/api";
  import { navigate } from "../lib/router";
  import { DIFFICULTY_LABEL, type LyricLine, type Note, type Settings, type Song } from "../lib/types";

  let { id }: { id: string } = $props();

  type Phase = "loading" | "uncalibrated" | "denied" | "error" | "countdown" | "playing" | "paused";

  let phase = $state<Phase>("loading");
  let message = $state("");
  let pauseReason = $state("");
  let countdown = $state(3);
  let song = $state<Song | null>(null);
  let settings = $state<Settings | null>(null);
  let canvas = $state<HTMLCanvasElement>();

  // Stato del gioco fuori dalla reattività: cambia a ogni lettura del microfono.
  let notes: Note[] = [];
  let lines: LyricLine[] = [];
  let range: PitchRange = pitchRange([]);
  let keeper = new ScoreKeeper([], "normal");
  let trail: { t: number; midi: number }[] = [];
  let voice: number | null = null;
  let lastVoiceAt = -Infinity;
  let latencyS = 0;
  let ctx: AudioContext | null = null;
  let player: SongPlayer | null = null;
  let mic: Mic | null = null;
  let micLost = false;
  let frame = 0;
  let countdownTimer: ReturnType<typeof setTimeout> | undefined;
  let disposed = false;

  onMount(() => {
    start();
    frame = requestAnimationFrame(loop);
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      disposed = true;
      cancelAnimationFrame(frame);
      clearTimeout(countdownTimer);
      document.removeEventListener("visibilitychange", onVisibility);
      mic?.close();
      player?.dispose();
      ctx?.close();
    };
  });

  async function start() {
    try {
      const [loadedSong, loadedSettings, loadedNotes] = await Promise.all([getSong(id), getSettings(), getNotes(id)]);
      song = loadedSong;
      settings = loadedSettings;
      notes = loadedNotes;
      range = pitchRange(notes);
      // Un brano senza testo si gioca comunque.
      const rawLines = await getLyrics(id).catch(() => [] as LyricLine[]);
      const offset = loadedSong.lyrics_offset_s;
      lines = rawLines.map((line) => ({
        ...line,
        start: line.start + offset,
        end: line.end + offset,
        words: line.words?.map((w) => ({ ...w, start: w.start + offset, end: w.end + offset })) ?? null,
      }));
      if (!loadedSettings.calibrated) {
        phase = "uncalibrated";
        return;
      }
      await prepare();
    } catch (e) {
      phase = "error";
      message = (e as Error).message;
    }
  }

  async function prepare() {
    if (!settings) return;
    phase = "loading";
    try {
      latencyS = settings.latency_ms / 1000;
      ctx = new AudioContext();
      await openMic();
      player = await SongPlayer.load(ctx, id);
      if (disposed) return;
      player.setGuideVolume(settings.guide_volume);
      player.onEnded = finish;
      restart();
    } catch (e) {
      if (e instanceof MicDeniedError) {
        phase = "denied";
      } else {
        phase = "error";
        message = (e as Error).message;
      }
    }
  }

  async function openMic() {
    if (!ctx || !settings) return;
    mic?.close();
    mic = await Mic.open(ctx, settings.mic_device_id);
    micLost = false;
    mic.onReading = onReading;
    mic.onLost = () => {
      micLost = true;
      pause("Il microfono si è scollegato. Ricollegalo e riprendi.");
    };
  }

  // Il punteggio è guidato dalle letture del microfono, mai dai fotogrammi.
  function onReading(reading: PitchReading) {
    if (!player || !player.playing) return;
    const t = player.timeAt(reading.t) - latencyS;
    keeper.feed(t, reading.midi);
    if (reading.midi === null) {
      voice = null;
      return;
    }
    const target = targetNote(notes, t);
    voice = target ? foldToOctave(reading.midi, target.pitch) : reading.midi;
    lastVoiceAt = t;
    trail.push({ t, midi: voice });
    if (trail.length > 600) trail.splice(0, trail.length - 400);
  }

  function restart() {
    if (!player || !settings) return;
    clearTimeout(countdownTimer);
    player.pause();
    player.seek(0);
    keeper = new ScoreKeeper(notes, settings.difficulty);
    trail = [];
    voice = null;
    pauseReason = "";
    countdown = 3;
    phase = "countdown";
    tick();
  }

  function tick() {
    countdownTimer = setTimeout(() => {
      countdown -= 1;
      if (countdown > 0) {
        tick();
        return;
      }
      ctx?.resume();
      player?.play();
      phase = "playing";
    }, 1000);
  }

  function pause(reason = "") {
    if (phase !== "playing") return;
    player?.pause();
    pauseReason = reason;
    phase = "paused";
  }

  async function resume() {
    if (phase !== "paused" || !player) return;
    try {
      if (micLost) await openMic();
      await ctx?.resume();
      pauseReason = "";
      player.play();
      phase = "playing";
    } catch (e) {
      pauseReason = e instanceof MicDeniedError ? "Permesso del microfono negato." : (e as Error).message;
    }
  }

  function finish() {
    if (!settings) return;
    keeper.finish();
    sessionStorage.setItem("lastResult", JSON.stringify({ songId: id, difficulty: settings.difficulty, ...keeper.result() }));
    navigate({ name: "result", id });
  }

  function exit() {
    navigate({ name: "library" });   // senza salvare alcun punteggio
  }

  function onVisibility() {
    if (document.hidden) pause("Il gioco è andato in pausa perché la scheda non era visibile.");
  }

  function onKey(event: KeyboardEvent) {
    if (event.code === "Space") {
      event.preventDefault();
      if (phase === "playing") pause();
      else if (phase === "paused") resume();
    } else if (event.code === "Escape" && phase === "playing") {
      pause();
    }
  }

  function onGuideVolume(event: Event) {
    if (!settings) return;
    settings.guide_volume = Number((event.currentTarget as HTMLInputElement).value);
    player?.setGuideVolume(settings.guide_volume);
    putSettings($state.snapshot(settings)).catch(() => {});
  }

  function loop() {
    frame = requestAnimationFrame(loop);
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

    const now = player ? player.heardTime() : 0;
    // Senza letture recenti la voce non c'è più: il pallino sparisce.
    if (voice !== null && player && player.timeAt(ctx!.currentTime) - latencyS - lastVoiceAt > 0.15) voice = null;
    const { current, next } = lineAt(lines, now);
    drawFrame(g, {
      width, height, now, notes, range,
      hits: (i) => keeper.hitSegments(i),
      trail,
      voice: phase === "playing" ? voice : null,
      score: keeper.score,
      multiplier: keeper.multiplier,
      progress: player ? now / player.duration : 0,
      line: current >= 0 ? { text: lines[current].text, sung: sungFraction(lines[current], now) } : null,
      nextLine: next >= 0 ? lines[next].text : null,
    });
  }
</script>

<svelte:window onkeydown={onKey} />

<canvas bind:this={canvas}></canvas>

<div class="hud">
  {#if phase === "playing"}
    <button onclick={() => pause()}>Pausa</button>
  {/if}
  {#if song && (phase === "playing" || phase === "countdown")}
    <span class="muted">{[song.title, settings ? DIFFICULTY_LABEL[settings.difficulty] : ""].filter(Boolean).join(" · ")}</span>
  {/if}
</div>

{#if phase !== "playing"}
  <div class="overlay" class:light={phase === "countdown"}>
    {#if phase === "loading"}
      <p class="big">Preparo il brano…</p>
    {:else if phase === "countdown"}
      <p class="count">{countdown}</p>
    {:else if phase === "uncalibrated"}
      <div class="panel box">
        <h2>Ritardo del microfono non ancora tarato</h2>
        <p class="muted">Senza taratura il punteggio può risultare in anticipo o in ritardo rispetto alla tua voce. Ci vuole meno di un minuto.</p>
        <div class="row">
          <button class="primary" onclick={() => navigate({ name: "calibration" })}>Tara ora</button>
          <button onclick={prepare}>Gioca lo stesso</button>
          <button onclick={exit}>Esci</button>
        </div>
      </div>
    {:else if phase === "denied"}
      <div class="panel box">
        <h2>Serve il microfono</h2>
        <p>Il gioco ha bisogno del microfono. Consenti l'accesso dall'icona del lucchetto nella barra degli indirizzi, poi ricarica.</p>
        <div class="row">
          <button class="primary" onclick={() => location.reload()}>Ricarica</button>
          <button onclick={exit}>Esci</button>
        </div>
      </div>
    {:else if phase === "error"}
      <div class="panel box">
        <h2>Non riesco ad avviare il brano</h2>
        <p class="error">{message}</p>
        <div class="row"><button onclick={exit}>Torna alla libreria</button></div>
      </div>
    {:else if phase === "paused"}
      <div class="panel box">
        <h2>In pausa</h2>
        {#if pauseReason}<p class="warn">{pauseReason}</p>{/if}
        {#if settings}
          <label class="volume">
            Voce guida
            <input type="range" min="0" max="1" step="0.05" value={settings.guide_volume} oninput={onGuideVolume} />
            <span class="muted">{Math.round(settings.guide_volume * 100)}%</span>
          </label>
        {/if}
        <div class="row">
          <button class="primary" onclick={resume}>Riprendi</button>
          <button onclick={restart}>Ricomincia</button>
          <button onclick={exit}>Esci</button>
        </div>
        <p class="muted hint">Spazio: pausa e ripresa. Uscendo il punteggio non viene salvato.</p>
      </div>
    {/if}
  </div>
{/if}

<style>
  canvas { position: fixed; inset: 0; width: 100vw; height: 100vh; display: block; }
  .hud { position: fixed; top: 44px; left: 24px; display: flex; align-items: center; gap: 0.75rem; }
  .hud button { padding: 0.25rem 0.7rem; font-size: 0.9rem; opacity: 0.8; }
  .overlay {
    position: fixed; inset: 0; display: flex; align-items: center; justify-content: center;
    background: rgba(10, 12, 18, 0.72);
  }
  .overlay.light { background: transparent; pointer-events: none; }
  .box { max-width: 520px; padding: 1.5rem; }
  .box p { margin: 0 0 1rem; }
  .big { font-size: 1.3rem; color: var(--muted); }
  .count { font-size: 9rem; font-weight: 800; color: var(--warn); margin: 0; text-shadow: 0 4px 24px rgba(0, 0, 0, 0.6); }
  .warn { color: var(--warn); }
  .volume { display: flex; align-items: center; gap: 0.75rem; margin-bottom: 1rem; }
  .volume input { flex: 1; accent-color: var(--accent); }
  .hint { font-size: 0.85rem; margin: 1rem 0 0 !important; }
</style>
