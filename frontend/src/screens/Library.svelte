<script lang="ts">
  import { onMount } from "svelte";
  import { addFile, addUrl, deleteSong, getSettings, getSystem, listSongs, retrySong } from "../lib/api";
  import { navigate } from "../lib/router";
  import { formatDuration, songStatus } from "../lib/status";
  import { DIFFICULTY_LABEL, stageLabel, type Difficulty, type Song, type SystemInfo } from "../lib/types";

  let songs = $state<Song[]>([]);
  let system = $state<SystemInfo | null>(null);
  let difficulty = $state<Difficulty>("normal");
  let url = $state("");
  let adding = $state(false);
  let addError = $state("");
  let loadError = $state("");
  let dragging = $state(false);
  let loaded = $state(false);
  let timer: ReturnType<typeof setTimeout> | undefined;

  // Si interroga il server ogni secondo solo finché c'è qualcosa in elaborazione.
  async function refresh() {
    clearTimeout(timer);
    try {
      songs = await listSongs();
      loadError = "";
      loaded = true;
    } catch (error) {
      loadError = (error as Error).message;
    }
    if (loadError) timer = setTimeout(refresh, 3000);
    else if (songs.some((song) => song.queue_position !== null)) timer = setTimeout(refresh, 1000);
  }

  onMount(() => {
    refresh();
    getSystem().then((info) => (system = info)).catch(() => {});
    getSettings().then((settings) => (difficulty = settings.difficulty)).catch(() => {});
    return () => clearTimeout(timer);
  });

  async function add(job: () => Promise<Song>) {
    adding = true;
    addError = "";
    try {
      await job();
    } catch (error) {
      addError = (error as Error).message;
    } finally {
      adding = false;
      await refresh();
    }
  }

  async function submitUrl(event: SubmitEvent) {
    event.preventDefault();
    const value = url.trim();
    if (!value) return;
    await add(() => addUrl(value));
    if (!addError) url = "";
  }

  async function addFiles(files: FileList | null | undefined) {
    for (const file of Array.from(files ?? [])) {
      await add(() => addFile(file));
      if (addError) break;
    }
  }

  function onDrop(event: DragEvent) {
    event.preventDefault();
    dragging = false;
    addFiles(event.dataTransfer?.files);
  }

  async function retry(song: Song) {
    try {
      await retrySong(song.id);
    } catch (error) {
      addError = (error as Error).message;
    }
    await refresh();
  }

  async function remove(song: Song) {
    if (!confirm(`Eliminare "${song.title}" dalla libreria?`)) return;
    try {
      await deleteSong(song.id);
    } catch (error) {
      addError = (error as Error).message;
    }
    await refresh();
  }
</script>

<main class="page">
  <div class="topbar">
    <h1>Karaoke</h1>
    <button onclick={() => navigate({ name: "settings" })}>Impostazioni</button>
  </div>

  {#if system && !system.gpu}
    <div class="banner">Scheda grafica non disponibile: l'elaborazione sarà lenta.</div>
  {/if}
  {#if loadError}
    <div class="banner">{loadError}</div>
  {/if}

  <section
    class="panel add"
    class:dragging
    ondragover={(event) => { event.preventDefault(); dragging = true; }}
    ondragleave={() => (dragging = false)}
    ondrop={onDrop}
    role="group"
    aria-label="Aggiungi un brano"
  >
    <form class="row" onsubmit={submitUrl}>
      <input type="text" placeholder="Incolla un link di YouTube" bind:value={url} disabled={adding} />
      <button class="primary" type="submit" disabled={adding || !url.trim()}>
        {adding ? "Aggiungo…" : "Aggiungi"}
      </button>
      <label class="file">
        oppure scegli un file audio
        <input type="file" accept="audio/*,video/*" multiple disabled={adding}
               onchange={(event) => { addFiles(event.currentTarget.files); event.currentTarget.value = ""; }} />
      </label>
    </form>
    <p class="muted hint">Puoi anche trascinare qui i file audio.</p>
    {#if addError}
      <p class="error">{addError}</p>
    {/if}
  </section>

  {#if loaded && songs.length === 0}
    <p class="muted empty">La libreria è vuota. Aggiungi il primo brano qui sopra.</p>
  {/if}

  <ul class="songs">
    {#each songs as song (song.id)}
      {@const status = songStatus(song)}
      {@const record = song.scores[difficulty]}
      <li class="panel song">
        <div class="info">
          <div class="title">{song.title}</div>
          <div class="muted">
            {[song.artist || "Artista sconosciuto", formatDuration(song.duration_s)].filter(Boolean).join(" · ")}
          </div>

          {#if status.kind === "processing"}
            <div class="state working">
              Passo {status.step} di 5 · {stageLabel(status.stage)}{#if status.detail} · {status.detail}{/if}
            </div>
            <progress max="5" value={status.step - 0.5}></progress>
          {:else if status.kind === "queued"}
            <div class="state muted">In coda (posizione {status.position})</div>
          {:else if status.kind === "error"}
            <div class="state error">{stageLabel(status.stage)}: {status.message}</div>
          {:else if record}
            <div class="state muted">
              Record ({DIFFICULTY_LABEL[difficulty]}): {record.score.toLocaleString("it-IT")} punti ·
              {"★".repeat(record.stars)}{"☆".repeat(5 - record.stars)}
            </div>
          {:else if song.lyrics_source === "none"}
            <div class="state muted">Senza testo</div>
          {/if}
        </div>

        <div class="row actions">
          {#if status.kind === "ready"}
            <button class="primary" onclick={() => navigate({ name: "game", id: song.id })}>Gioca</button>
            <button onclick={() => navigate({ name: "edit", id: song.id })}>Modifica</button>
            <button onclick={() => navigate({ name: "verify", id: song.id })}>Verifica</button>
          {:else if status.kind === "error"}
            <button onclick={() => retry(song)}>Riprova</button>
          {/if}
          {#if status.kind === "ready" || status.kind === "error"}
            <button class="danger" onclick={() => remove(song)}>Elimina</button>
          {/if}
        </div>
      </li>
    {/each}
  </ul>
</main>

<style>
  .add { margin-bottom: 1.25rem; border-style: dashed; }
  .add.dragging { border-color: var(--accent); background: var(--panel-2); }
  .add input[type="text"] { flex: 1; min-width: 240px; }
  .file { color: var(--accent); cursor: pointer; }
  .file input { display: none; }
  .hint { margin: 0.6rem 0 0; font-size: 0.9rem; }
  .empty { text-align: center; margin-top: 3rem; }
  .songs { list-style: none; margin: 0; padding: 0; display: grid; gap: 0.75rem; }
  .song { display: flex; align-items: center; justify-content: space-between; gap: 1rem; flex-wrap: wrap; }
  .info { min-width: 0; flex: 1; }
  .title { font-weight: 600; font-size: 1.05rem; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .state { margin-top: 0.35rem; font-size: 0.92rem; }
  .working { color: var(--warn); }
  progress { width: 100%; max-width: 320px; height: 6px; margin-top: 0.3rem; accent-color: var(--accent); }
</style>
