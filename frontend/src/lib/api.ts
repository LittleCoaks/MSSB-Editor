// Typed wrappers over the Python server's JSON API.

export interface EntrySummary {
  id: number; offset: number; disc_size: number; size: number; compressed: boolean;
  lookback_bits: number; repeat_bits: number; kind: string; ntex: number; nsec: number; naud: number;
  module: string; symbol: string; archive: string; name: string; refs: string[];
  label: string; names: string[]; known: string; thumb: number; twin: number; tag: string;
}
export interface Texture { n: number; section: number | null; index: number; width: number; height: number; fmt: string; mips: number; offset: number; size: number; tlut: number; flags: string }
export interface Section { index: number; offset: number; size: number; kind: string; magic: number; ntex: number }
export interface AudioStream { pos: number; kind: string; rate: number; channels: number; seconds: number; samples: number; loop: boolean; label?: string; note?: number }
export interface SfxInfo { id: number; macro: number; priority: number; streams: number[] }
export interface SongInfo { n: number; offset: number; bpm: number; tracks: number; notes: number; seconds: number; tempo: number; channels: number[] }
export interface GroupInfo { id: number; type: number; kind: string; samples: number; sfx: number }
export interface ModelInfo { section: number; offset: number; meshes: string[]; triangles: number; textures: number[] }
export interface BankInfo { key: string; entry: number; section: number; label: string; sequences: number | null }
export interface EntryDetail extends EntrySummary {
  file_kind: string; hvqm4: Record<string, string | number> | null; sections: Section[]; textures: Texture[];
  audio: AudioStream[]; sfx: SfxInfo[]; songs: SongInfo[]; group: GroupInfo | null; models: ModelInfo[]; banks: BankInfo[]; parts: string[]; variants: { slot: number; name: string; entry: number }[]; file_name: string;
}
export interface IndexDoc { meta: Record<string, any>; archive: string | null; archive_size: number; entries: EntrySummary[]; error?: string }
export interface GameInfo {
  setting: string | null; layout: string; iso: string | null; files_dir: string | null; sys_dir: string | null; dol: string | null;
  archive: string | null; archive_source: string | null; writable: boolean; ok: boolean; problem: string; entries: number;
  error?: string | null; default_dump?: string | null; edit_ready?: boolean;
  thumbs?: { running: boolean; done: number; total: number };
}
export interface CatalogGroup { id: string; name: string; items: number[]; thumb: string | null }
export interface CatalogCategory { id: string; name: string; count: number; groups: CatalogGroup[] }
export interface Catalog { categories: CatalogCategory[]; names: Record<string, string> }
export interface Track {
  file: string; label: string; custom: boolean; category: string; exists: boolean; size: number; seconds: number;
  stock_size: number | null; loop_end: number | null; in_table: boolean; modified: boolean; has_backup: boolean;
  mismatch: boolean; entry: number | null;
}
export interface MusicInfo { root: string | null; tracks: Track[]; numpy: boolean; backends: string[]; can_install_decoder: boolean }
export interface Job { id: string; state: 'running' | 'done' | 'error'; progress: number; error?: string; result?: any; dest?: string; track?: string }
export interface ReplaceResult { offset: number; disc_size: number; size: number; in_place: boolean; descriptors: number }
export interface ReplacedTexture { n: number; width: number; height: number; fmt: string; levels: number; source_width: number; source_height: number; resized: boolean; palette: number; truncated: number }
export interface SlotInfo { slot: number; name: string; clone_of: number | null; clone_of_name: string | null; copy: boolean | null; inplace: number }
export interface CloneResult { source: number; target: number; copy: boolean; copied: number; inplace: string[]; shared: number; appended_bytes: number; source_name: string; target_name: string }
export interface MovieInfo { ready: boolean; helper: boolean; job: string | null; width?: number; height?: number; frames?: number; fps?: number; sample_rate?: number }
export interface FsListing { path: string; parent: string | null; dirs: string[]; files: { name: string; size: number }[]; layout: string }
export interface RosterSlot { slot: number; name: string }
export interface RosterEntry { id: number; name: string; slot: number; slots: RosterSlot[]; thumb: number | null; model_entry: number | null; sound_entry: number | null; variants: number }
export interface RosterModel { role: string; entry: number; section: number; meshes: string[]; triangles: number; textures: number; size: number; models: ModelInfo[]; poses?: number; bat_pose?: number | null }
export interface RosterVariant { slot: number; name: string; texture_entry: number | null; own: boolean }
export interface RosterBank { key: string; entry: number; track: number; category: string; label: string; sequences: string[]; named: boolean }
export interface RosterSounds { entry: number; group: number | null; samples: { n: number; seconds: number; rate: number; label: string }[]; sfx: SfxInfo[] }
export interface RosterFile { entry: number; role: string; kind: string; size: number; slot: number | null; textures: number; audio: number }
export interface StadiumFile { entry: number; textures: number; size: number; slots?: number[]; sky?: { rgb: number[]; night: boolean } | null; models?: { section: number; meshes: string[]; triangles: number; textures: number }[]; triangles?: number; sections?: number }
export interface StadiumProp { entry: number; name: string; triangles: number; textures: number; models: { section: number; meshes: string[]; triangles: number; textures: number }[] }
export interface StadiumEntry { id: number; name: string; files: StadiumFile[]; thumb: number | null }
export interface StadiumDetail extends StadiumEntry { props: StadiumProp[] }
export interface UpdateStatus { current: string; latest: string | null; available: boolean; asset: { name: string; url: string; size: number } | null; notes: string; url: string; checked_at: number; error: string | null; can_install: boolean }
export interface UpdateInfo { version: string; releases: string; check_updates: boolean; repo: string; status: UpdateStatus | null }
export interface RosterDetail extends Omit<RosterEntry, 'variants'> {
  models: RosterModel[]; variants: RosterVariant[]; parts: RosterModel[]; banks: RosterBank[]; sounds: RosterSounds | null; files: RosterFile[]; viewer_parts: string[]
}

async function j<T>(url: string, init?: RequestInit): Promise<T> {
  const r = await fetch(url, init)
  const d = await r.json()
  if (!r.ok && d && d.error) throw new Error(d.error)
  return d as T
}

export const api = {
  index: () => j<IndexDoc>('/api/index'),
  game: () => j<GameInfo>('/api/game'),
  setGame: (path: string) => j<GameInfo>('/api/game?path=' + encodeURIComponent(path), { method: 'POST' }),
  dumpGame: (only: string) => j<{ job: string }>('/api/game/dump?only=' + encodeURIComponent(only), { method: 'POST' }),
  fs: (path: string) => j<FsListing>('/api/fs?path=' + encodeURIComponent(path)),
  job: (id: string) => j<Job>('/api/job/' + id),
  catalog: () => j<Catalog>('/api/catalog'),
  entry: (id: number) => j<EntryDetail>('/api/entry/' + id),
  hex: (id: number, offset: number, length = 4096) => j<{ offset: number; total: number; hex: string }>(`/api/entry/${id}/hex?offset=${offset}&length=${length}`),
  extract: (id: number, opts: { png?: boolean; wav?: boolean; model?: string }) =>
    j<{ written: string[] }>(`/api/entry/${id}/extract?${opts.png ? 'png=1' : ''}${opts.wav ? '&wav=1' : ''}${opts.model ? '&model=' + opts.model : ''}`),
  music: () => j<MusicInfo>('/api/music'),
  musicJob: (id: string) => j<Job>('/api/music/job/' + id),
  musicRestore: (track: string) => j<{ ok: boolean }>('/api/music/restore?track=' + encodeURIComponent(track), { method: 'POST' }),
  musicRoot: (path: string) => j<{ root: string }>('/api/music/root?path=' + encodeURIComponent(path), { method: 'POST' }),
  musicInstall: (fd: FormData) => j<{ job: string }>('/api/music/install', { method: 'POST', body: fd }),
  modified: () => j<{ ids: number[] }>('/api/modified'),
  thumbs: () => j<{ running: boolean; done: number; total: number }>('/api/thumbs'),
  replace: (id: number, fd: FormData) => j<ReplaceResult>(`/api/entry/${id}/replace`, { method: 'POST', body: fd }),
  replaceTexture: (id: number, n: number, fd: FormData) =>
    j<ReplaceResult & { texture: ReplacedTexture }>(`/api/entry/${id}/tex/${n}/replace`, { method: 'POST', body: fd }),
  movie: (id: number) => j<MovieInfo>(`/api/entry/${id}/movie`),
  prepareMovie: (id: number) => j<{ ready?: boolean; job?: string }>(`/api/entry/${id}/movie/prepare`, { method: 'POST' }),
  exportMovie: (id: number) => j<{ written: string[]; dest: string }>(`/api/entry/${id}/movie/export`),
  characters: () => j<{ slots: SlotInfo[]; editable: boolean }>('/api/characters'),
  cloneCharacter: (source: number, target: number, copy: boolean) => j<CloneResult>(`/api/characters/clone?source=${source}&target=${target}&copy=${copy ? 1 : 0}`, { method: 'POST' }),
  restoreCharacter: (target: number) => j<{ ok: boolean }>(`/api/characters/restore?target=${target}`, { method: 'POST' }),
  restoreEntry: (id: number) => j<{ ok: boolean }>(`/api/entry/${id}/restore`, { method: 'POST' }),
  roster: () => j<{ characters: RosterEntry[] }>('/api/roster'),
  character: (id: number) => j<RosterDetail>('/api/roster/' + id),
  exportCharacter: (id: number, what: string) => j<{ written: string[]; dest: string }>(`/api/roster/${id}/export?what=${what}`),
  update: (check = false, force = false) => j<UpdateInfo>(`/api/update?${check ? 'check=1' : ''}${force ? '&force=1' : ''}`),
  updateSettings: (checkUpdates: boolean) => j<{ check_updates: boolean; repo: string }>(`/api/update/settings?check_updates=${checkUpdates ? 1 : 0}`, { method: 'POST' }),
  installUpdate: () => j<{ job: string }>('/api/update/install', { method: 'POST' }),
  stadiums: () => j<{ stadiums: StadiumEntry[] }>('/api/stadiums'),
  stadium: (id: number) => j<StadiumDetail>('/api/stadiums/' + id),
}

export const urls = {
  tex: (id: number, n: number) => `/api/entry/${id}/tex/${n}.png?d=2`,  // d = decoder version, busts the browser cache
  thumb: (id: number) => `/api/thumb/${id}.png?d=2`,
  audio: (id: number, n: number) => `/api/entry/${id}/audio/${n}.wav`,
  audioDownload: (id: number, n: number) => `/api/entry/${id}/audio/${n}.wav?download=1`,
  midi: (id: number, n: number) => `/api/entry/${id}/song/${n}.mid`,
  songWav: (id: number, n: number) => `/api/entry/${id}/song/${n}.wav`,
  songMix: (id: number, ns: number[], loops = 1) => `/api/entry/${id}/song/mix.wav?songs=${ns.join(',')}&loops=${loops}`,
  movieFrame: (id: number, n: number) => `/api/entry/${id}/movie/frame/${n}.jpg`,
  movieAudio: (id: number) => `/api/entry/${id}/movie/audio.wav`,
  glb: (id: number, sec: number, anim?: string, parts?: string, variant?: number, pose?: number) => `/api/entry/${id}/model/${sec}.glb?anim=${encodeURIComponent(anim ?? '')}&parts=${parts ?? ''}${variant !== undefined ? '&variant=' + variant : ''}${pose !== undefined ? '&pose=' + pose : ''}`,
  scene: (id: number) => `/api/entry/${id}/model/all.glb`,
  collision: (id: number) => `/api/entry/${id}/collision.json`,
  obj: (id: number, sec: number, pose?: number) => `/api/entry/${id}/model/${sec}.obj${pose !== undefined ? '?pose=' + pose : ''}`,
  data: (id: number) => `/api/entry/${id}/data`,
  raw: (id: number) => `/api/entry/${id}/raw`,
}

// Native dialogs when running inside the pywebview window.
type Native = { pick_iso(): Promise<string | null>; pick_folder(): Promise<string | null>; pick_audio(): Promise<string | null> }
export const native = (): Native | null => (window as any).pywebview?.api ?? null

export const kb = (n: number) => n >= 1048576 ? (n / 1048576).toFixed(1) + ' MB' : n >= 1024 ? (n / 1024).toFixed(1) + ' KB' : n + ' B'
export const hex = (n: number, w = 8) => '0x' + n.toString(16).padStart(w, '0')

export const KIND_LABEL: Record<string, string> = {
  container: 'asset pack', textures: 'textures', anim: 'animation', hvqm4: 'movie', adgc: 'sound bank',
  'dsp-adpcm': 'sound', 'dtk-adpcm': 'music', musyx: 'sound effects', songs: 'sequenced music', text: 'text', geopalette: 'model', unknown: 'data', rel: 'code',
}

export let catalogNames: Record<string, string> = {}
export function setCatalogNames(n: Record<string, string>) { catalogNames = n }
export function friendlyName(e: EntrySummary): string {
  const n = catalogNames[String(e.id)]
  if (n) return n
  if (e.known) return e.known
  if (e.label) return e.label.replace(/\.(gpc|tpl)$/, '')
  return `${KIND_LABEL[e.kind] ?? e.kind} #${e.id}`
}

export async function pollJob(id: string, fetcher: (id: string) => Promise<Job>, onProgress: (j: Job) => void): Promise<Job> {
  for (;;) {
    const jb = await fetcher(id)
    onProgress(jb)
    if (jb.state !== 'running') return jb
    await new Promise(r => setTimeout(r, 400))
  }
}
