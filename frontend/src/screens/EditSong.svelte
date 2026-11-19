<script lang="ts">
  import { onMount } from "svelte";
  import { getLyrics, getSong, patchSong, putLyrics, retrySong } from "../lib/api";
  import type { LyricLine, Song } from "../lib/types";

  let { id }: { id: string } = $props();

  const SOURCE_LABEL = { lrclib: "Da LRCLIB", whisper: "Trascritto dalla voce", none: "Nessun testo" } as const;

  let song = $state<Song | null>(null);
  let title = $state("");
  let artist = $state("");
  let language = $state("");
  let offset = $state(0);
  let lines = $state.raw<LyricLine[]>([]);
  let texts = $state<string[]>([]);
  let error = $state("");
  let notice = $state("");
  let searching = $state(false);
  let offsetTimer: ReturnType<typeof setTimeout> | undefined;
  let pollTimer: ReturnType<typeof setTimeout> | undefined;

  const textChanged = $derived(texts.some((text, i) => text.trim() !== lines[i]?.text));
  const dataChanged = $derived(
    song !== null && (title.trim() !== song.title || artist.trim() !== song.artist || language.trim().toLowerCase() !== (song.language_user ? song.language ?? "" : "")),
  );

  onMount(() => {
    load();
    return () => {
      clearTimeout(offsetTimer);
      clearTimeout(pollTimer);
    };
  });

  function show(loaded: Song) {
    song = loaded;
    title = loaded.title;
    artist = loaded.artist;
    language = loaded.language_user ? loaded.language ?? "" : "";
    offset = loaded.lyrics_offset_s;
  }

  async function loadLyrics() {
    lines = await getLyrics(id).catch(() => [] as LyricLine[]);
    texts = lines.map((line) => line.text);
  }

  async function load() {
    try {
      show(await getSong(id));
      await loadLyrics();
    } catch (e) {
      error = (e as Error).message;
    }
  }

  async function saveData(): Promise<boolean> {
    try {
      show(await patchSong(id, { title: title.trim(), artist: artist.trim(), language: language.trim() || null }));
      error = "";
      notice = "Dati salvati.";
      return true;
    } catch (e) {
      error = (e as Error).message;
      return false;
    }
  }

  async function saveText() {
    try {
      lines = await putLyrics(id, texts);
      texts = lines.map((line) => line.text);
      error = "";
      notice = "Testo salvato.";
    } catch (e) {
      error = (e as Error).message;
    }
  }

  function onOffset() {
    clearTimeout(offsetTimer);
    offsetTimer = setTimeout(async () => {
      try {
        song = await patchSong(id, { lyrics_offset_s: offset });
        error = "";
      } catch (e) {
        error = (e as Error).message;
      }
    }, 300);
  }

  async function searchAgain() {
    if (!confirm("Cerco di nuovo il testo: le correzioni fatte a mano andranno perse. Continuo?")) return;
    if (dataChanged && !(await saveData())) return;
    try {
      searching = true;
      notice = "";
      await retrySong(id, "lyrics");
      poll();
    } catch (e) {
      searching = false;
      error = (e as Error).message;
    }
  }

  // Si aspetta che il passo del testo finisca, poi si ricaricano le righe.
  function poll() {
    pollTimer = setTimeout(async () => {
      try {
        const current = await getSong(id);
        if (current.queue_position !== null) return poll();
        show(current);
        await loadLyrics();
        notice = current.lyrics_source === "none" ? "Nessun testo trovato." : `Testo aggiornato: ${SOURCE_LABEL[current.lyrics_source ?? "none"].toLowerCase()}.`;
      } catch (e) {
        error = (e as Error).message;
      }
      searching = false;
    }, 1000);
  }

  function clock(seconds: number): string {
    const minutes = Math.floor(seconds / 60);
    return `${minutes}:${(seconds - minutes * 60).toFixed(1).padStart(4, "0")}`;
  }
</script>

<main class="page">
  <div class="topbar">
    <div>
      <a href="#/library">← Libreria</a>
      <h1>Modifica brano</h1>
    </div>
  </div>

  {#if error}<div class="banner">{error}</div>{/if}

  {#if song}
    <section class="panel">
      <h2>Dati</h2>
      <div class="fields">
        <label>Titolo <input type="text" bind:value={title} /></label>
        <label>Artista <input type="text" bind:value={artist} /></label>
        <label>
          Lingua
          <input type="text" class="short" maxlength="2" placeholder="auto" bind:value={language} />
          <span class="muted">
            codice a due lettere (en, it, de…); vuoto = automatica{#if song.language && !song.language_user}, rilevata: {song.language}{/if}
          </span>
        </label>
      </div>
      <div class="row">
        <button class="primary" onclick={saveData} disabled={!dataChanged}>Salva dati</button>
      </div>
    </section>

    <section class="panel">
      <h2>Testo</h2>
      <div class="row source">
        <span>Origine: <strong>{SOURCE_LABEL[song.lyrics_source ?? "none"]}</strong></span>
        <button onclick={searchAgain} disabled={searching}>{searching ? "Cerco…" : "Cerca di nuovo il testo"}</button>
      </div>
      <p class="muted">Dopo aver corretto artista, titolo o lingua, cerca di nuovo: prima su LRCLIB, poi trascrivendo la voce.</p>

      <label class="offset">
        Sposta tutto il testo
        <input type="range" min="-5" max="5" step="0.1" bind:value={offset} oninput={onOffset} />
        <output>{offset > 0 ? "+" : ""}{offset.toFixed(1)} s</output>
        <span class="muted">{offset === 0 ? "" : offset > 0 ? "arriva più tardi" : "arriva prima"}</span>
      </label>

      {#if lines.length === 0}
        <p class="muted">Questo brano non ha testo: si gioca comunque, seguendo solo le barre.</p>
      {:else}
        <div class="lines">
          {#each lines as line, i (i)}
            <span class="time">{clock(line.start)}</span>
            <input type="text" bind:value={texts[i]} />
          {/each}
        </div>
        <div class="row">
          <button class="primary" onclick={saveText} disabled={!textChanged}>Salva testo</button>
          <span class="muted">Si correggono le parole; i tempi delle righe restano quelli.</span>
        </div>
      {/if}
    </section>

    {#if notice}<p class="notice">{notice}</p>{/if}
  {/if}
</main>

<style>
  section { margin-bottom: 1rem; }
  .fields { display: grid; gap: 0.7rem; margin-bottom: 1rem; }
  .fields label { display: grid; grid-template-columns: 80px minmax(200px, 420px) 1fr; align-items: center; gap: 0.75rem; }
  .fields .short { width: 80px; }
  .source { justify-content: space-between; }
  .offset { display: flex; align-items: center; gap: 0.75rem; margin: 1rem 0; flex-wrap: wrap; }
  .offset input { width: 320px; accent-color: var(--accent); }
  .offset output { font-variant-numeric: tabular-nums; min-width: 4.5rem; }
  .lines { display: grid; grid-template-columns: auto 1fr; gap: 0.35rem 0.75rem; align-items: center; margin: 1rem 0; }
  .time { color: var(--dim); font-variant-numeric: tabular-nums; font-size: 0.9rem; }
  .lines input { width: 100%; }
  .notice { color: var(--good); }
  h1 { margin-top: 0.3rem; }
</style>
