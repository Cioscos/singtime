import type {
  Difficulty, LyricLine, Note, NoteParams, PitchData, ScoreRecord, Settings, Song, Stage, SystemInfo,
} from "./types";

export class ApiError extends Error {
  constructor(message: string, readonly status: number) {
    super(message);
    this.name = "ApiError";
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, init);
  } catch {
    throw new ApiError("Server non raggiungibile: è ancora avviato?", 0);
  }
  if (!response.ok) {
    let message = `Errore ${response.status}`;
    try {
      const body = await response.json();
      if (typeof body?.detail === "string") message = body.detail;
    } catch {
      // risposta senza corpo JSON: resta il messaggio generico
    }
    throw new ApiError(message, response.status);
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

function json(method: string, body: unknown): RequestInit {
  return { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
}

const song = (id: string) => `/api/songs/${encodeURIComponent(id)}`;

export const getSystem = () => request<SystemInfo>("/api/system");
export const listSongs = () => request<Song[]>("/api/songs");
export const addUrl = (url: string) => request<Song>("/api/songs/url", json("POST", { url }));

export function addFile(file: File): Promise<Song> {
  const form = new FormData();
  form.append("file", file, file.name);
  return request<Song>("/api/songs/file", { method: "POST", body: form });
}

export const getSong = (id: string) => request<Song>(song(id));

export type SongPatch = Partial<Pick<Song, "title" | "artist" | "language" | "lyrics_offset_s">>;
export const patchSong = (id: string, patch: SongPatch) => request<Song>(song(id), json("PATCH", patch));

export const deleteSong = (id: string) => request<void>(song(id), { method: "DELETE" });
export const retrySong = (id: string, fromStage: Stage | null = null) =>
  request<Song>(`${song(id)}/retry`, json("POST", { from_stage: fromStage }));

export const getNotes = async (id: string) => (await request<{ notes: Note[] }>(`${song(id)}/notes`)).notes;
export const getSwiftF0Notes = async (id: string) =>
  (await request<{ notes: Note[] }>(`${song(id)}/notes-swiftf0`)).notes;
export const getLyrics = async (id: string) => (await request<{ lines: LyricLine[] }>(`${song(id)}/lyrics`)).lines;
export const getPitch = (id: string) => request<PitchData>(`${song(id)}/pitch`);
export const putLyrics = async (id: string, texts: string[]) =>
  (await request<{ lines: LyricLine[] }>(`${song(id)}/lyrics`, json("PUT", { texts }))).lines;
export const previewNotes = async (id: string, params: NoteParams) =>
  (await request<{ notes: Note[] }>(`${song(id)}/notes/preview`, json("POST", params))).notes;

export const applyNotes = async (id: string, params: NoteParams) =>
  (await request<{ notes: Note[] }>(`${song(id)}/notes/apply`, json("POST", params))).notes;

export const audioUrl = (id: string, which: "vocals" | "instrumental") => `${song(id)}/audio/${which}`;

export interface ScoreBody {
  difficulty: Difficulty;
  score: number;
  accuracy: number;
  stars: number;
}
export const postScore = (id: string, body: ScoreBody) =>
  request<Partial<Record<Difficulty, ScoreRecord>>>(`${song(id)}/scores`, json("POST", body));

export const getNoteParams = () => request<NoteParams>("/api/note-params");
export const putNoteParams = (params: NoteParams) => request<NoteParams>("/api/note-params", json("PUT", params));
export const getSettings = () => request<Settings>("/api/settings");
export const putSettings = (settings: Settings) => request<Settings>("/api/settings", json("PUT", settings));
