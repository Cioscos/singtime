<script lang="ts">
  import { onMount } from "svelte";
  import { getSong, postScore } from "../lib/api";
  import { clearLastResult, isNewRecord, readLastResult, type LastResult } from "../lib/last-result";
  import { navigate } from "../lib/router";
  import { DIFFICULTY_LABEL, type ScoreRecord, type Song } from "../lib/types";

  let { id }: { id: string } = $props();

  let song = $state<Song | null>(null);
  let result = $state<LastResult | null>(null);
  let previous = $state<ScoreRecord | undefined>(undefined);
  let record = $state(false);
  let loaded = $state(false);
  let error = $state("");
  let unsaved = $state(false);
  let saving = $state(false);

  onMount(async () => {
    // Il risultato si mostra subito; resta da parte finché il server non l'ha salvato.
    result = readLastResult(sessionStorage, id);
    try {
      song = await getSong(id);
      if (result) {
        previous = song.scores[result.difficulty];
        record = isNewRecord(result.score, previous);
      }
    } catch (e) {
      error = (e as Error).message;
    }
    if (result) await send();
    loaded = true;
  });

  async function send() {
    if (!result || saving) return;
    saving = true;
    try {
      await postScore(id, {
        difficulty: result.difficulty, score: result.score, accuracy: result.accuracy, stars: result.stars,
      });
      clearLastResult(sessionStorage);
      unsaved = false;
      error = "";
    } catch (e) {
      unsaved = true;
      error = `Punteggio non ancora salvato: ${(e as Error).message}`;
    } finally {
      saving = false;
    }
  }

  const points = (value: number) => value.toLocaleString("it-IT");
</script>

<main class="page center">
  {#if error}
    <div class="banner">
      {error}
      {#if unsaved}<button onclick={send} disabled={saving}>{saving ? "Salvo…" : "Riprova a salvare"}</button>{/if}
    </div>
  {/if}

  {#if result}
    <p class="muted">{song?.title ?? ""}{song?.artist ? ` · ${song.artist}` : ""}</p>
    {#if record}<p class="record">Nuovo record!</p>{/if}
    <p class="score">{points(result.score)}</p>
    <p class="stars" aria-label="{result.stars} stelle su 5">
      {"★".repeat(result.stars)}<span class="off">{"★".repeat(5 - result.stars)}</span>
    </p>
    <p class="detail">
      Sulla nota per il <strong>{Math.round(result.accuracy * 100)}%</strong> del tempo ·
      difficoltà {DIFFICULTY_LABEL[result.difficulty]}
    </p>
    {#if previous}
      <p class="muted">Record precedente: {points(previous.score)} punti</p>
    {/if}
  {:else if loaded}
    <p class="muted">Nessun risultato da mostrare per questo brano.</p>
  {/if}

  <div class="row buttons">
    <button class="primary" onclick={() => navigate({ name: "game", id })}>Rigioca</button>
    <button onclick={() => navigate({ name: "library" })}>Libreria</button>
  </div>
</main>

<style>
  .center { text-align: center; padding-top: 12vh; }
  .banner button { margin-left: 0.75rem; }
  .score { font-size: 5rem; font-weight: 800; margin: 0.2rem 0; }
  .stars { font-size: 2.4rem; color: var(--warn); margin: 0; letter-spacing: 0.15em; }
  .stars .off { color: var(--line); }
  .record { color: var(--good); font-weight: 700; font-size: 1.3rem; margin: 0.5rem 0 0; }
  .detail { font-size: 1.1rem; margin: 1rem 0 0.4rem; }
  .buttons { justify-content: center; margin-top: 2rem; }
</style>
