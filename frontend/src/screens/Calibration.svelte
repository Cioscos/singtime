<script lang="ts">
  import { onMount } from "svelte";
  import { detectOnsets, estimateLatencyMs, onsetCorrection } from "../game/latency";
  import { Mic, MicDeniedError } from "../game/mic";
  import { getSettings, putSettings } from "../lib/api";
  import type { Settings } from "../lib/types";

  const CLICKS = 8;
  const CLICK_SPACING_S = 0.6;

  type Phase = "idle" | "running" | "done" | "failed";

  let settings = $state<Settings | null>(null);
  let phase = $state<Phase>("idle");
  let measuredMs = $state<number | null>(null);
  let heard = $state(0);
  let error = $state("");
  let saved = $state(false);
  let ctx: AudioContext | null = null;
  let mic: Mic | null = null;

  onMount(() => {
    getSettings().then((loaded) => (settings = loaded)).catch((e) => (error = (e as Error).message));
    return cleanup;
  });

  function cleanup() {
    mic?.close();
    mic = null;
    ctx?.close();
    ctx = null;
  }

  /** Un clic breve e secco: facile da riconoscere per il microfono. */
  function scheduleClick(context: AudioContext, when: number) {
    const oscillator = context.createOscillator();
    const gain = context.createGain();
    oscillator.frequency.value = 1000;
    gain.gain.setValueAtTime(0.9, when);
    gain.gain.exponentialRampToValueAtTime(0.001, when + 0.03);
    oscillator.connect(gain).connect(context.destination);
    oscillator.start(when);
    oscillator.stop(when + 0.04);
  }

  async function run() {
    if (!settings) return;
    cleanup();
    phase = "running";
    error = "";
    saved = false;
    measuredMs = null;
    try {
      ctx = new AudioContext();
      mic = await Mic.open(ctx, settings.mic_device_id);
      const readings: { t: number; rms: number }[] = [];
      mic.onReading = (reading) => readings.push({ t: reading.t, rms: reading.rms });

      const first = ctx.currentTime + 0.6;
      const clicks = Array.from({ length: CLICKS }, (_, i) => first + i * CLICK_SPACING_S);
      clicks.forEach((when) => scheduleClick(ctx!, when));
      const totalMs = (0.6 + CLICKS * CLICK_SPACING_S + 0.4) * 1000;
      await new Promise((resolve) => setTimeout(resolve, totalMs));

      // Soglia adattata al volume: ben sopra il fruscio, ben sotto il picco dei clic.
      const sorted = readings.map((r) => r.rms).sort((a, b) => a - b);
      const floor = sorted[Math.floor(sorted.length / 2)] ?? 0;
      const peak = sorted[sorted.length - 1] ?? 0;
      const threshold = Math.max(0.02, floor * 4, peak * 0.35);
      const correction = onsetCorrection(ctx.sampleRate);
      const onsets = detectOnsets(readings, threshold).map((t) => t + correction);
      heard = clicks.filter((click) => onsets.some((o) => o >= click && o <= click + 0.5)).length;
      const estimate = estimateLatencyMs(clicks, onsets);
      measuredMs = estimate === null ? null : Math.round(estimate);
      phase = estimate === null ? "failed" : "done";
    } catch (e) {
      phase = "idle";
      error = e instanceof MicDeniedError
        ? "Permesso del microfono negato. Consentilo dall'icona del lucchetto nella barra degli indirizzi, poi riprova."
        : (e as Error).message;
    } finally {
      cleanup();
    }
  }

  async function save() {
    if (!settings || measuredMs === null) return;
    try {
      settings = await putSettings({ ...$state.snapshot(settings), latency_ms: measuredMs, calibrated: true });
      saved = true;
    } catch (e) {
      error = (e as Error).message;
    }
  }
</script>

<main class="page">
  <div class="topbar">
    <div>
      <a href="#/settings">← Impostazioni</a>
      <h1>Taratura del ritardo</h1>
    </div>
  </div>

  <section class="panel">
    <ol>
      <li>Indossa le cuffie e alza un po' il volume.</li>
      <li>Avvicina una cuffia al microfono, fino a toccarlo.</li>
      <li>Premi Avvia e resta in silenzio per cinque secondi.</li>
    </ol>

    {#if error}<p class="error">{error}</p>{/if}

    {#if phase === "running"}
      <p class="working">Sto emettendo {CLICKS} clic e ascolto dal microfono…</p>
    {:else if phase === "done"}
      <p class="result">Ritardo misurato: <strong>{measuredMs} ms</strong> <span class="muted">({heard} clic su {CLICKS} sentiti)</span></p>
      {#if settings?.calibrated}
        <p class="muted">Valore salvato finora: {Math.round(settings.latency_ms)} ms.</p>
      {/if}
    {:else if phase === "failed"}
      <p class="error">Non ho sentito i clic: alza il volume o avvicina la cuffia.</p>
    {/if}

    <div class="row">
      {#if phase === "done"}
        <button class="primary" onclick={save} disabled={saved}>{saved ? "Salvato" : "Salva"}</button>
        <button onclick={run}>Riprova</button>
      {:else}
        <button class="primary" onclick={run} disabled={phase === "running" || !settings}>
          {phase === "failed" ? "Riprova" : "Avvia"}
        </button>
      {/if}
      {#if saved}<a href="#/library">Torna alla libreria</a>{/if}
    </div>
  </section>

  <p class="muted note">
    Misura quanto tempo passa da quando il computer emette un suono a quando il microfono lo sente.
    Il gioco usa questo valore per giudicare la tua voce nel momento giusto. Puoi correggerlo a mano dalle impostazioni.
  </p>
</main>

<style>
  ol { margin: 0 0 1rem; padding-left: 1.2rem; line-height: 1.7; }
  .working { color: var(--warn); }
  .result { font-size: 1.15rem; }
  .note { font-size: 0.9rem; margin-top: 1rem; }
  h1 { margin-top: 0.3rem; }
</style>
