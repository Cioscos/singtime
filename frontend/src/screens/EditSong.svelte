<script lang="ts">
  import { onMount } from "svelte";
  import { getSong, patchSong, retrySong } from "../lib/api";
  import { applyLabel, LYRICS_CHOICES, lyricsProblem } from "../lib/status";
  import type { LyricsChoice, Song } from "../lib/types";
  import LyricsEditor from "./LyricsEditor.svelte";

  let { id }: { id: string } = $props();

  const SOURCE_LABEL = {
    lrclib: "Da LRCLIB", aligned: "Da LRCLIB, allineato alla voce", whisper: "Trascritto dalla voce",
    manual: "Scritto a mano", none: "Nessun testo",
  } as const;

  const HELP: Record<LyricsChoice, string> = {
    auto: "Prima su LRCLIB: se il testo combacia con la voce uso quello; se i tempi non combaciano, o c'è solo il testo di un'altra versione, ne allineo le parole alla voce; se non c'è, trascrivo la voce.",
    lrclib: "Il testo scritto dai volontari di LRCLIB, anche quando i tempi non combaciano con la voce. Servono artista e titolo giusti.",
    aligned: "Le parole di LRCLIB, di qualunque versione del brano, con i tempi presi da questa registrazione parola per parola. Le righe che qui non si cantano spariscono. Servono artista e titolo giusti; la prima volta scarico un modello da 1,2 GB.",
    whisper: "Trascrivo la voce isolata: non serve che il brano sia su LRCLIB, ma sul cantato qualche parola o frase può essere sbagliata o mancare.",
    none: "Si gioca seguendo solo le barre.",
  };
  const LOSE = "il testo e i tempi sistemati a mano andranno persi. Continuo?";
  const CONFIRM: Record<LyricsChoice, string> = {
    auto: `Cerco di nuovo il testo: ${LOSE}`,
    lrclib: `Prendo il testo da LRCLIB: ${LOSE}`,
    aligned: `Prendo il testo da LRCLIB e lo allineo alla voce: ${LOSE}`,
    whisper: `Trascrivo di nuovo la voce: ${LOSE}`,
    none: `Tolgo il testo da questo brano: ${LOSE}`,
  };

  let song = $state<Song | null>(null);
  let tab = $state<"text" | "data">("text");
  let title = $state("");
  let artist = $state("");
  let language = $state("");
  let choice = $state<LyricsChoice>("auto");
  let error = $state("");
  let notice = $state("");
  let searching = $state(false);
  let textDirty = $state(false);
  let pollTimer: ReturnType<typeof setTimeout> | undefined;

  const dataChanged = $derived(
    song !== null && (title.trim() !== song.title || artist.trim() !== song.artist || language.trim().toLowerCase() !== (song.language_user ? song.language ?? "" : "")),
  );

  onMount(() => {
    load();
    return () => clearTimeout(pollTimer);
  });

  // Chiudere o ricaricare la pagina con il testo a metà chiede conferma.
  $effect(() => {
    if (!textDirty) return;
    const warn = (event: BeforeUnloadEvent) => event.preventDefault();
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  });

  function show(loaded: Song) {
    song = loaded;
    title = loaded.title;
    artist = loaded.artist;
    language = loaded.language_user ? loaded.language ?? "" : "";
  }

  async function load() {
    try {
      show(await getSong(id));
      choice = song?.lyrics_choice ?? "auto";
      if (song && song.queue_position !== null) {
        // Il brano è già in lavorazione (per esempio una ricerca lanciata prima di ricaricare la pagina):
        // si aspetta che finisca, altrimenti si lavorerebbe su righe che stanno per cambiare.
        searching = true;
        poll();
      }
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

  // Dopo un salvataggio del testo cambiano origine e stato della ricerca; i campi dei dati restano come sono.
  async function onTextSaved() {
    try {
      song = await getSong(id);
      error = "";
    } catch (e) {
      error = (e as Error).message;
    }
  }

  async function applySource() {
    const hasText = song !== null && song.lyrics_source !== null && song.lyrics_source !== "none";
    if ((hasText || textDirty) && !confirm(CONFIRM[choice])) return;
    if (dataChanged && !(await saveData())) return;
    try {
      searching = true;   // l'editor si chiude: riparte dal testo nuovo quando la ricerca finisce
      textDirty = false;
      notice = "";
      show(await patchSong(id, { lyrics_choice: choice }));
      await retrySong(id, "lyrics");
      poll();
    } catch (e) {
      searching = false;
      error = (e as Error).message;
    }
  }

  // Si aspetta che il passo del testo finisca, poi l'editor ricarica le righe.
  function poll() {
    pollTimer = setTimeout(async () => {
      try {
        const current = await getSong(id);
        if (current.queue_position !== null) return poll();
        show(current);
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

  function leave(event: MouseEvent) {
    if (textDirty && !confirm("Ci sono modifiche al testo non salvate. Esco lo stesso?")) event.preventDefault();
  }
</script>

<main class="page" class:full={tab === "text"}>
  <div class="topbar">
    <div>
      <a href="#/library" onclick={leave}>← Libreria</a>
      <h1>Modifica: {song?.title ?? "…"}</h1>
      {#if song}
        <div class="muted">{[song.artist, SOURCE_LABEL[song.lyrics_source ?? "none"]].filter(Boolean).join(" · ")}</div>
      {/if}
    </div>
    <div class="tabs" role="tablist">
      <button role="tab" aria-selected={tab === "text"} class:on={tab === "text"} onclick={() => (tab = "text")}>
        Testo e tempi{#if textDirty}<span class="dot" title="Modifiche non salvate"></span>{/if}
      </button>
      <button role="tab" aria-selected={tab === "data"} class:on={tab === "data"} onclick={() => (tab = "data")}>
        Dati e fonte del testo
      </button>
    </div>
  </div>

  {#if error}<div class="banner">{error}</div>{/if}

  {#if song}
    <!-- L'editor resta montato anche mentre si guardano i dati: le modifiche non salvate non si perdono. -->
    <div class="text" hidden={tab !== "text"}>
      {#if searching}
        <p class="muted">Sto cercando il testo: l'editor torna appena ho finito.</p>
      {:else if !song.playable}
        <p class="muted">Il brano non è ancora pronto: il testo si sistema quando l'elaborazione è finita.</p>
      {:else}
        <LyricsEditor {song} active={tab === "text"} bind:dirty={textDirty} onsaved={onTextSaved} />
      {/if}
    </div>

    {#if tab === "data"}
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
        <h2>Fonte del testo</h2>
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
        <p class="muted">
          Parole e tempi si sistemano nella scheda <button class="link" onclick={() => (tab = "text")}>Testo e tempi</button>.
        </p>
      </section>

      {#if notice}<p class="notice">{notice}</p>{/if}
    {/if}
  {/if}
</main>

<style>
  /* L'editor occupa tutta la finestra: la timeline resta ferma e scorre solo l'elenco delle righe. */
  .full { max-width: 1400px; height: 100%; display: flex; flex-direction: column; padding-bottom: 1rem; }
  .full .topbar { margin-bottom: 0.9rem; }
  .text:not([hidden]) { flex: 1; min-height: 0; display: flex; flex-direction: column; }
  .tabs { display: flex; gap: 0.3rem; }
  .tabs button { border-radius: 8px 8px 0 0; border-bottom: 2px solid transparent; background: none; color: var(--muted); }
  .tabs button.on { color: var(--text); border-bottom-color: var(--accent); background: var(--panel); }
  .dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; background: var(--warn); margin-left: 0.45rem; }
  section { margin-bottom: 1rem; }
  .fields { display: grid; gap: 0.7rem; margin-bottom: 1rem; }
  .fields label { display: grid; grid-template-columns: 80px minmax(200px, 420px) 1fr; align-items: center; gap: 0.75rem; }
  .fields .short { width: 80px; }
  .source { gap: 0.75rem; margin: 0.6rem 0 0.4rem; }
  .source label { display: flex; align-items: center; gap: 0.6rem; }
  .link { background: none; border: none; padding: 0; color: var(--accent); text-decoration: underline; }
  .notice { color: var(--good); }
  h1 { margin-top: 0.3rem; }
</style>
