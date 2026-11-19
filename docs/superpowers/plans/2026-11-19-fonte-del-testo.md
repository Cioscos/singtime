# Scelta della fonte del testo — piano di implementazione

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** chi gioca sceglie, brano per brano, da dove arriva il testo: automatica, LRCLIB, trascrizione, nessuno.

**Architecture:** un campo `lyrics_choice` nei dati del brano, letto da `find_lyrics`; un campo `lyrics_note` con la spiegazione dell'ultima ricerca. La schermata Modifica salva la scelta con la PATCH esistente e rilancia il passo `lyrics` con la rotta `retry` esistente.

**Tech Stack:** quello del progetto (FastAPI, Svelte 5, pytest, vitest).

**Spec:** `docs/superpowers/specs/2026-11-19-fonte-del-testo-design.md`

## Global Constraints

- Testi dell'interfaccia e messaggi in italiano, con gli accenti.
- I `meta.json` già su disco non hanno i campi nuovi: devono caricarsi con i valori predefiniti.
- La tolleranza sulla durata di LRCLIB (3 s) non cambia.

## Review Focus

- Brano senza artista o titolo con scelta "lrclib": niente eccezioni, testo vuoto e nota che spiega.
- Scelta "lrclib" e LRCLIB irraggiungibile: testo vuoto con nota, nessuna trascrizione.
- Valore di `lyrics_choice` sconosciuto nella PATCH: 422, il brano non cambia.
- Ricerca riuscita dopo una fallita: la nota vecchia non deve restare.
- Scelta "none" su un brano che aveva testo: le righe spariscono davvero dal file.

---

### Task 1: backend — la scelta guida la ricerca

**Files:**
- Modify: `backend/karaoke/models.py`, `backend/karaoke/pipeline/lyrics.py`, `backend/karaoke/pipeline/runner.py`, `backend/karaoke/api.py`
- Test: `backend/tests/test_lyrics.py`, `backend/tests/test_runner.py`, `backend/tests/test_api.py`, `backend/tests/test_library.py`

**Interfaces:**
- Produces: `LyricsChoice = Literal["auto", "lrclib", "whisper", "none"]` in `models.py`;
  `SongMeta.lyrics_choice: LyricsChoice = "auto"`, `SongMeta.lyrics_note: str | None = None`;
  `find_lyrics(meta, vocals, notes, fetch=…, transcribe_fn=…) -> tuple[list[LyricLine], LyricsSource, str | None, str | None]`
  (righe, origine, lingua rilevata, nota); `SongPatch.lyrics_choice: LyricsChoice | None`.

- [ ] **Step 1: test che falliscono** (in `test_lyrics.py`, con gli aiuti `meta`, `sung`, `WHISPER_LINE` già presenti)
  - `test_choice_lrclib_keeps_text_the_voice_check_would_drop`: LRC che parte a 40 s con canto da 10 s, `meta(lyrics_choice="lrclib")` → origine `"lrclib"`, nota `None`, `transcribe_fn` mai chiamata.
  - `test_choice_lrclib_without_a_match_leaves_no_text_and_says_why`: `fetch` restituisce `None` → `([], "none", None, nota)` con `"LRCLIB"` nella nota; `transcribe_fn` mai chiamata. Stesso esito con `artist=""`.
  - `test_choice_whisper_skips_lrclib`: `fetch` che fa `pytest.fail` → origine `"whisper"`.
  - `test_choice_none_removes_the_text`: né `fetch` né `transcribe_fn` chiamate → `([], "none", None, None)`.
  - `test_auto_says_why_lrclib_was_dropped`: il caso di `test_find_drops_lrclib_text_timed_on_another_version` → nota che contiene `"LRCLIB"` e `"canto"`.
  - I test esistenti di `find_lyrics` spacchettano quattro valori; quelli riusciti con LRCLIB o senza LRCLIB hanno nota `None`.
  - `test_runner.py`: `test_the_lyrics_note_is_saved_and_cleared` — un `find_lyrics` finto che restituisce prima una nota e poi `None`: `meta.lyrics_note` la segue. I tre `find_lyrics` finti esistenti restituiscono quattro valori.
  - `test_api.py`: `test_patch_lyrics_choice` — PATCH `{"lyrics_choice": "whisper"}` → 200 e campo salvato; `{"lyrics_choice": "boh"}` → 422 e campo invariato.
  - `test_library.py`: `test_old_meta_without_lyrics_choice_loads_as_auto` — un `meta.json` senza i due campi si carica con `"auto"` e `None`.
- [ ] **Step 2:** `uv run pytest backend/tests -q` → i test nuovi falliscono (campo sconosciuto, tre valori invece di quattro).
- [ ] **Step 3: implementazione.** Campi in `SongMeta`; in `find_lyrics` un ramo per scelta (il controllo `lrc_mismatch` solo con `"auto"`); note in italiano: `"LRCLIB non ha un testo sincronizzato per questa versione del brano"`, `"Per cercare su LRCLIB servono artista e titolo"`, `"Il testo di LRCLIB non combacia con la voce (<motivo>): ho trascritto la voce"`; `stage_lyrics` salva `lyrics_note` insieme a `lyrics_source`; `SongPatch` accetta `lyrics_choice`.
- [ ] **Step 4:** `uv run pytest backend/tests -q` → tutto verde.
- [ ] **Step 5:** commit `feat: scelta della fonte del testo (backend)`.

### Task 2: frontend — la scelta nella schermata Modifica

**Files:**
- Modify: `frontend/src/lib/types.ts`, `frontend/src/lib/status.ts`, `frontend/src/screens/EditSong.svelte`
- Test: `frontend/src/lib/status.test.ts`

**Interfaces:**
- Consumes: `Song.lyrics_choice`, `Song.lyrics_note` dal server; `patchSong`, `retrySong`.
- Produces: `LyricsChoice` e `LYRICS_CHOICES: { value: LyricsChoice; label: string }[]` in `status.ts`;
  `applyLabel(choice: LyricsChoice): string`.

- [ ] **Step 1: test che falliscono** in `status.test.ts`: `LYRICS_CHOICES` elenca nell'ordine `auto, lrclib, whisper, none` con le etichette "Automatica", "LRCLIB", "Trascrizione dalla voce", "Nessun testo"; `applyLabel("none")` è "Togli il testo", per le altre "Cerca il testo".
- [ ] **Step 2:** `npx vitest run` → falliscono.
- [ ] **Step 3: implementazione.** Nel pannello Testo: `<select>` "Fonte del testo" + pulsante con `applyLabel`; al clic conferma, salva i dati modificati, `patchSong(id, { lyrics_choice })`, `retrySong(id, "lyrics")`, poi l'attesa esistente. Sotto l'origine, `song.lyrics_note` quando c'è. Il testo d'aiuto sotto il pannello descrive la voce scelta.
- [ ] **Step 4:** `npx vitest run`, `npm run check`, `npm run build` → verdi.
- [ ] **Step 5: nel browser** (Edge headless, `cdp.mjs`): su Home scegliere "LRCLIB" → origine "Da LRCLIB", prima riga a 0:38.8; "Automatica" → trascrizione, con la nota sul motivo; "Nessun testo" → nessuna riga; rimettere "Automatica".
- [ ] **Step 6:** commit `feat: scelta della fonte del testo (schermata Modifica)`.
