<script lang="ts">
  import { onMount } from "svelte";
  import { listMics, Mic, MicDeniedError } from "../game/mic";
  import { noteName } from "../game/pitch-math";
  import { getSettings, putSettings } from "../lib/api";
  import { navigate } from "../lib/router";
  import { DIFFICULTY_LABEL, type Difficulty, type Settings } from "../lib/types";

  const DIFFICULTIES: Difficulty[] = ["easy", "normal", "hard"];
  const DIFFICULTY_HINT: Record<Difficulty, string> = {
    easy: "vale entro 2 semitoni dalla nota",
    normal: "vale entro 1 semitono",
    hard: "vale entro mezzo semitono",
  };

  let settings = $state<Settings | null>(null);
  let mics = $state<{ id: string; label: string }[]>([]);
  let error = $state("");
  let testing = $state(false);
  let note = $state<string | null>(null);
  let level = $state(0);
  let saveTimer: ReturnType<typeof setTimeout> | undefined;
  let ctx: AudioContext | null = null;
  let mic: Mic | null = null;

  onMount(() => {
    getSettings()
      .then((loaded) => (settings = loaded))
      .catch((e) => (error = (e as Error).message));
    listMics().then((found) => (mics = found)).catch(() => {});
    return () => {
      clearTimeout(saveTimer);
      stopTest();
    };
  });

  // Ogni modifica si salva da sola, poco dopo l'ultimo tocco.
  function save() {
    clearTimeout(saveTimer);
    saveTimer = setTimeout(async () => {
      if (!settings) return;
      try {
        await putSettings($state.snapshot(settings));
        error = "";
      } catch (e) {
        error = (e as Error).message;
      }
    }, 300);
  }

  async function startTest() {
    if (!settings) return;
    stopTest();
    try {
      ctx = new AudioContext();
      mic = await Mic.open(ctx, settings.mic_device_id);
      mic.onReading = (reading) => {
        level = Math.min(1, reading.rms * 6);
        note = reading.midi === null ? null : noteName(reading.midi);
      };
      mic.onLost = () => {
        stopTest();
        error = "Il microfono si è scollegato.";
      };
      testing = true;
      error = "";
      mics = await listMics(); // dopo il permesso compaiono i nomi veri
    } catch (e) {
      stopTest();
      error = e instanceof MicDeniedError
        ? "Permesso del microfono negato. Consentilo dall'icona del lucchetto nella barra degli indirizzi, poi riprova."
        : (e as Error).message;
    }
  }

  function stopTest() {
    mic?.close();
    mic = null;
    ctx?.close();
    ctx = null;
    testing = false;
    note = null;
    level = 0;
  }

  function onMicChange() {
    save();
    if (testing) startTest();
  }
</script>

<main class="page">
  <div class="topbar">
    <div>
      <a href="#/library">← Libreria</a>
      <h1>Impostazioni</h1>
    </div>
  </div>

  <div class="banner">Usa le cuffie: con le casse il microfono sente la musica.</div>
  {#if error}<p class="error">{error}</p>{/if}

  {#if settings}
    <section class="panel">
      <h2>Microfono</h2>
      <div class="row">
        <select bind:value={settings.mic_device_id} onchange={onMicChange}>
          <option value={null}>Predefinito del sistema</option>
          {#each mics as device (device.id)}
            <option value={device.id}>{device.label}</option>
          {/each}
        </select>
        {#if testing}
          <button onclick={stopTest}>Ferma la prova</button>
        {:else}
          <button class="primary" onclick={startTest}>Prova il microfono</button>
        {/if}
      </div>
      {#if testing}
        <div class="meter">
          <div class="note">{note ?? "—"}</div>
          <div class="level"><div style:width="{level * 100}%"></div></div>
          <p class="muted">Canta una nota tenuta: qui compare la nota rilevata. In silenzio resta il trattino.</p>
        </div>
      {/if}
    </section>

    <section class="panel">
      <h2>Ritardo del microfono</h2>
      <div class="row">
        <input type="number" step="1" min="-200" max="1000" bind:value={settings.latency_ms} oninput={save} />
        <span class="muted">millisecondi</span>
        <button onclick={() => navigate({ name: "calibration" })}>Tara</button>
        {#if !settings.calibrated}<span class="warn">Non ancora tarato</span>{/if}
      </div>
      <p class="muted">La taratura misura quanto tempo passa tra l'audio e il microfono. Rifalla se cambi cuffie o microfono.</p>
    </section>

    <section class="panel">
      <h2>Voce guida</h2>
      <div class="row">
        <input type="range" min="0" max="1" step="0.05" bind:value={settings.guide_volume} oninput={save} />
        <span class="muted">{Math.round(settings.guide_volume * 100)}%</span>
      </div>
      <p class="muted">Quanto si sente la voce originale sopra la base. A zero canti da solo.</p>
    </section>

    <section class="panel">
      <h2>Difficoltà</h2>
      <div class="choices">
        {#each DIFFICULTIES as difficulty (difficulty)}
          <label>
            <input type="radio" name="difficulty" value={difficulty} bind:group={settings.difficulty} onchange={save} />
            <strong>{DIFFICULTY_LABEL[difficulty]}</strong>
            <span class="muted">— {DIFFICULTY_HINT[difficulty]}</span>
          </label>
        {/each}
      </div>
    </section>
  {/if}
</main>

<style>
  section { margin-bottom: 1rem; }
  section p { margin: 0.6rem 0 0; font-size: 0.92rem; }
  select { min-width: 280px; }
  input[type="number"] { width: 110px; }
  input[type="range"] { width: 280px; accent-color: var(--accent); }
  .warn { color: var(--warn); }
  .meter { margin-top: 1rem; }
  .note { font-size: 2.4rem; font-weight: 700; color: var(--warn); min-height: 3rem; }
  .level { height: 8px; background: var(--panel-2); border-radius: 4px; overflow: hidden; max-width: 420px; }
  .level div { height: 100%; background: var(--good); transition: width 60ms linear; }
  .choices { display: grid; gap: 0.5rem; }
  h1 { margin-top: 0.3rem; }
</style>
