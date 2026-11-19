<script lang="ts">
  import { onMount } from "svelte";
  import { getLyrics, getSong, patchSong, putLyrics, retrySong } from "../lib/api";
  import { debounced } from "../lib/debounce";
  import { applyLabel, LYRICS_CHOICES, lyricsProblem } from "../lib/status";
  import type { LyricLine, LyricsChoice, Song } from "../lib/types";

  let { id }: { id: string } = $props();

  const SOURCE_LABEL = { lrclib: "Da LRCLIB", whisper: "Trascritto dalla voce", none: "Nessun testo" } as const;

  const HELP: Record<LyricsChoice, string> = {
    auto: "Prima su LRCLIB: se il testo combacia con la voce uso quello, altrimenti trascrivo la voce.",
    lrclib: "Il testo scritto dai volontari di LRCLIB, anche quando i tempi non combaciano con la voce. Servono artista e titolo giusti.",
    whisper: "Trascrivo la voce isolata: tempi precisi, ma qualche parola può essere sbagliata o mancare.",
    none: "Si gioca seguendo solo le barre.",
  };
  const LOSE = "le correzioni fatte a mano andranno perse. Continuo?";
  const CONFIRM: Record<LyricsChoice, string> = {
    auto: `Cerco di nuovo il testo: ${LOSE}`,
    lrclib: `Prendo il testo da LRCLIB: ${LOSE}`,
    whisper: `Trascrivo di nuovo la voce: ${LOSE}`,
    none: `Tolgo il testo da questo brano: ${LOSE}`,
  };

  let song = $state<Song | null>(null);
  let title = $state("");
  let artist = $state("");
  let language = $state("");
  let offset = $state(0);
  let choice = $state<LyricsChoice>("auto");
  let lines = $state.raw<LyricLine[]>([]);
  let texts = $state<string[]>([]);
  let error = $state("");
  let notice = $state("");
  let searching = $state(false);
  let pollTimer: ReturnType<typeof setTimeout> | undefined;

  const textChanged = $derived(texts.some((text, i) => text.trim() !== lines[i]?.text));
  const dataChanged = $derived(
    song !== null && (title.trim() !== song.title || artist.trim() !== song.artist || language.trim().toLowerCase() !== (song.language_user ? song.language ?? "" : "")),
  );

  onMount(() => {
    load();
    return () => {
      savingOffset.flush();   // uno spostamento appena fatto non deve perdersi lasciando la schermata
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
      choice = song?.lyrics_choice ?? "auto";
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

  const savingOffset = debounced(async () => {
    try {
      song = await patchSong(id, { lyrics_offset_s: offset });
      error = "";
    } catch (e) {
      error = (e as Error).message;
    }
  }, 300);
  const onOffset = () => savingOffset.schedule();

  async function applySource() {
    if (lines.length > 0 && !confirm(CONFIRM[choice])) return;
    if (dataChanged && !(await saveData())) return;
    try {
      searching = true;
      notice = "";
      show(await patchSong(id, { lyrics_choice: choice }));
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
        if (lyricsProblem(current) || current.lyrics_note) notice = "";      // il motivo compare accanto all'origine
        else if (current.lyrics_choice === "none") notice = "Testo tolto.";
        else if (current.lyrics_source === "none") notice = "Nessun testo trovato.";
        else {
          const label = SOURCE_LABEL[current.lyrics_source ?? "none"];
          notice = `Testo aggiornato: ${label[0].toLowerCase()}${label.slice(1)}.`;   // "da LRCLIB", non "da lrclib"
        }
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
      <p>Origine: <strong>{SOURCE_LABEL[song.lyrics_source ?? "none"]}</strong></p>
      {#if lyricsProblem(song) && !searching}
        <p class="error problem">L'ultima ricerca del testo non è riuscita: {lyricsProblem(song)}.</p>
      {:else if song.lyrics_note && !searching}
        <p class="muted lyrics-note">{song.lyrics_note}.</p>
      {/if}
      <div class="row source">
        <label>
          Fonte del testo
          <select bind:value={choice} disabled={searching}>
            {#each LYRICS_CHOICES as option (option.value)}
              <option value={option.value}>{option.label}</option>
            {/each}
          </select>
        </label>
        <button onclick={applySource} disabled={searching}>{searching ? "Cerco…" : applyLabel(choice)}</button>
      </div>
      <p class="muted">{HELP[choice]}</p>

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
  .source { gap: 0.75rem; margin: 0.6rem 0 0.4rem; }
  .source label { display: flex; align-items: center; gap: 0.6rem; }
  .offset { display: flex; align-items: center; gap: 0.75rem; margin: 1rem 0; flex-wrap: wrap; }
  .offset input { width: 320px; accent-color: var(--accent); }
  .offset output { font-variant-numeric: tabular-nums; min-width: 4.5rem; }
  .lines { display: grid; grid-template-columns: auto 1fr; gap: 0.35rem 0.75rem; align-items: center; margin: 1rem 0; }
  .time { color: var(--dim); font-variant-numeric: tabular-nums; font-size: 0.9rem; }
  .lines input { width: 100%; }
  .notice { color: var(--good); }
  h1 { margin-top: 0.3rem; }
</style>
