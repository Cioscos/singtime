// I tipi rispecchiano i JSON prodotti dal backend (vedi backend/karaoke/models.py).

export type Stage = "acquire" | "separate" | "pitch" | "notes" | "lyrics";
export const STAGES: Stage[] = ["acquire", "separate", "pitch", "notes", "lyrics"];

export interface StageState {
  status: "pending" | "running" | "done" | "error";
  error: string | null;
  detail: string | null;
}

export type Difficulty = "easy" | "normal" | "hard";
export const DIFFICULTY_LABEL: Record<Difficulty, string> = {
  easy: "Facile",
  normal: "Normale",
  hard: "Difficile",
};

export interface ScoreRecord {
  score: number;
  accuracy: number;
  stars: number;
  date: string;
}

export interface Song {
  id: string;
  title: string;
  artist: string;
  duration_s: number | null;
  source_kind: "youtube" | "file";
  source_ref: string;
  separator_model: string;
  pitch_tracker: string;
  language: string | null;
  language_user: boolean;
  lyrics_source: "lrclib" | "whisper" | "none" | null;
  lyrics_offset_s: number;
  created_at: string;
  stages: Record<Stage, StageState>;
  playable: boolean;
  queue_position: number | null;
  scores: Partial<Record<Difficulty, ScoreRecord>>;
}

/** Una barra: inizio e durata in secondi, altezza in semitoni MIDI con decimali. */
export interface Note {
  start: number;
  duration: number;
  pitch: number;
}

export interface Word {
  start: number;
  end: number;
  text: string;
}

export interface LyricLine {
  start: number;
  end: number;
  text: string;
  words: Word[] | null;
}

export interface PitchData {
  times: number[];
  midi: (number | null)[];
}

export interface Settings {
  mic_device_id: string | null;
  latency_ms: number;
  calibrated: boolean;
  guide_volume: number;
  difficulty: Difficulty;
}

export interface NoteParams {
  min_note_s: number;
  max_gap_s: number;
  vibrato_window_s: number;
  split_semitones: number;
  settle_s: number;
  merge_semitones: number;
  glide_window_s: number;
}

export interface SystemInfo {
  gpu: boolean;
  gpu_name: string | null;
}

const STAGE_LABELS: Record<Stage, string> = {
  acquire: "Scarico",
  separate: "Separo la voce",
  pitch: "Rilevo l'altezza",
  notes: "Creo le note",
  lyrics: "Cerco il testo",
};

export function stageLabel(stage: Stage): string {
  return STAGE_LABELS[stage];
}
