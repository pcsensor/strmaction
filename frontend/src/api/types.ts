export type ItemKind = 'movie' | 'series' | 'season' | 'episode' | 'video' | 'folder'
export type MatchState = 'pending' | 'auto' | 'manual' | 'failed' | 'skipped'
export type LibraryType = 'movie' | 'tv' | 'home' | 'course'

export interface ProgressInfo {
  position_ms: number
  duration_ms: number | null
  finished: boolean
  progress: number | null
  updated_at: string
}

export interface ItemSummary {
  id: number
  library_id: number
  parent_id: number | null
  kind: ItemKind
  title: string
  original_title: string | null
  year: number | null
  season_no: number | null
  episode_no: number | null
  overview_short: string | null
  rating: number | null
  poster: string | null
  poster_large: string | null
  backdrop: string | null
  backdrop_large: string | null
  logo: string | null
  color: string | null
  certification: string | null
  runtime_min: number | null
  provider: string | null
  match_state: MatchState
  status: string | null
  badges: string[]
  progress: ProgressInfo | null
  watched: boolean
  created_at: string
  updated_at: string
}

export interface CastMember {
  name: string
  role?: string | null
  avatar_url?: string | null
  avatar?: string | null
  kind?: string
}

export interface EpisodeSummary extends ItemSummary {
  episode_code: string | null
  still: string | null
  overview: string | null
  air_date: string | null
}

export interface MediaFileInfo {
  id: number
  version: string | null
  labels: string[]
  part: number | null
  size_bytes: number | null
  missing: boolean
  mtime: number | null
}

export interface ItemDetail extends ItemSummary {
  overview: string | null
  tagline: string | null
  genres: string[]
  cast: CastMember[]
  collection: { id?: number; name?: string } | null
  alt_titles: string[]
  external_ids: Record<string, string>
  provider_id: string | null
  locked_fields: string[]
  trailer_key: string | null
  air_date: string | null
  play_target_id?: number
  series_progress?: { watched: number; total: number; ratio: number }
}

export interface SeasonPayload {
  id: number
  season_no: number | null
  title: string
  poster: string | null
  episode_count: number
  watched_count: number
  episodes: EpisodeSummary[]
}

export interface LibraryInfo {
  id: number
  name: string
  root_path: string
  type: LibraryType
  language: string
  scan_cron: string | null
  enabled: boolean
  auto_scrape: boolean
  template: string | null
  provider_priority: string[] | null
  tvdb_season_type: string | null
  play_headers: Record<string, string>
  created_at: string
  last_scan_at: string | null
  counts?: Record<string, number>
}

export interface AncestorInfo {
  id: number
  title: string
  kind: ItemKind
}

export interface ItemDetailResponse {
  item: ItemDetail
  library: LibraryInfo | null
  series: ItemSummary | null
  parent: ItemSummary | null
  ancestors?: AncestorInfo[]
  folders?: ItemSummary[]
  videos?: ItemSummary[]
  seasons: SeasonPayload[]
  episodes: EpisodeSummary[]
  media_files: MediaFileInfo[]
  progress: ProgressInfo | null
  next_episode_id: number | null
  prev_episode_id: number | null
  needs_attention: boolean
}

export interface HeroItem extends ItemSummary {
  tagline: string | null
  overview: string | null
  genres: string[]
}

export interface ContinueItem extends ItemSummary {
  continue_item_id: number
  subtitle: string
  episode_code: string | null
}

export interface HomeRow {
  key: string
  title: string
  items: ItemSummary[]
}

export interface HomeData {
  hero: HeroItem[]
  continue: ContinueItem[]
  rows: HomeRow[]
  stats: { movies: number; series: number; episodes: number; videos: number }
  needs_attention: number
  libraries: LibraryInfo[]
}

export interface ItemListResponse {
  items: ItemSummary[]
  total: number
  page: number
  page_size: number
  pages: number
}

export interface SearchResponse {
  q: string
  items: ItemSummary[]
  total: number
  genres: { name: string; count: number }[]
}

export interface Candidate {
  provider: string
  provider_id: string
  title: string
  original_title: string | null
  year: number | null
  overview: string | null
  poster_url: string | null
  score: number
  kind: string
}

export interface PlaySubtitle {
  label: string
  lang: string
  filename: string
  format: string
  mime: string
  url: string
}

export type PlayMode =
  | 'builtin'
  | 'external_mpv'
  | 'browser_intent'
  | 'desktop_mpv'
  | 'copy'

export interface PlayResponse {
  mode: PlayMode
  requested_mode: PlayMode | 'auto'
  downgraded: boolean
  downgrade_reason:
    | 'requires_companion'
    | 'requires_android'
    | 'admin_only'
    | 'mpv_unavailable'
    | 'requires_desktop'
    | 'launch_failed'
    | null
  target: string
  action: string | null
  fallback_url: string | null
  tip: string
  warning?: string
  play_url: string
  resume_ms: number
  duration_ms: number | null
  item_id: number
  kind: ItemKind
  series_id: number | null
  library: string | null
  title: string
  headers: Record<string, string>
  headers_hint: string
  play_token: string
  play_token_expires_at: string
  progress_interval_ms: number
  fallback_on_error: boolean
  mpv_package: string
  subtitles: PlaySubtitle[]
  media_file_id: number
  progress_updated_at: string | null
  next_item_id: number | null
  next_title: string | null
  next_episode_code: string | null
}

export interface AuthState {
  needs_setup: boolean
  authenticated: boolean
  user: CurrentUser | null
  version?: string
}

// v0.9 多用户体系
export interface CurrentUser {
  id: number
  username: string
  role: 'admin' | 'user'
  display_name: string | null
}

export interface UserOut {
  id: number
  username: string
  display_name: string | null
  role: 'admin' | 'user'
  enabled: boolean
  library_count: number | null
  last_login_at: string | null
  created_at: string
  updated_at: string
}

export interface UserDetail {
  id: number
  username: string
  display_name: string | null
  role: 'admin' | 'user'
  enabled: boolean
  libraries: Array<{
    id: number
    name: string
    type: LibraryType
    enabled: boolean
  }>
  last_login_at: string | null
  created_at: string
  updated_at: string
  created_by: number | null
}

export interface UserCreateInput {
  username: string
  password: string
  display_name?: string
  role?: 'admin' | 'user'
  library_ids?: number[]
}

export interface UserPatchInput {
  password?: string
  display_name?: string
  enabled?: boolean
  role?: 'admin' | 'user'
}

export interface ProviderConfig {
  api_key: string
  base_url?: string
  proxy?: string
  rate_limit?: number
  concurrency?: number
  language?: string
  season_type?: string
  pin?: string
}

export interface AppSettings {
  server: { host?: string; port?: number; base_url?: string; data_dir?: string }
  auth: { username?: string; password_hash?: string }
  scraper: {
    language: string
    proxy: string
    auto_refresh_days: number
    match_threshold: number
    provider_priority: Record<string, string[]>
    tmdb: ProviderConfig
    tvdb: ProviderConfig
  }
  scanner: { ignore: string[]; follow_symlinks: boolean; max_depth: number }
  player: {
    mode: PlayMode | 'auto'
    progress_interval_ms: number
    play_token_ttl_hours: number
    fallback_on_error: boolean
    play_headers: Record<string, string>
    mpv_path: string
    mpv_extra_args: string[]
    mpv_package: string
    enable_progress: boolean
  }
  ui: { default_language: string; hero_rotate_ms: number }
}

export interface SettingsResponse {
  settings: AppSettings
  data_dir: string
  version: string
}

/** v1.2 用户级播放偏好；null 表示跟随全局默认。 */
export interface PlayerPreference {
  mode: PlayMode | 'auto' | null
  fallback_on_error: boolean | null
}

export interface PlayerPreferenceSummary {
  mode: PlayMode | 'auto'
  fallback_on_error: boolean
}

export interface MyPlayerResponse {
  overrides: PlayerPreference
  defaults: PlayerPreferenceSummary
  effective: PlayerPreferenceSummary
  /** 当前角色可选的播放方式；普通用户不含 desktop_mpv。 */
  allowed_modes: Array<PlayMode | 'auto'>
  /** 当前客户端实际能执行的播放方式。 */
  available_modes: Array<PlayMode | 'auto'>
  client: {
    is_companion: boolean
    is_android: boolean
    is_browser: boolean
  }
  /** 当前客户端按偏好解析后的实际播放方式。 */
  resolved_mode: PlayMode | 'auto'
}

export interface AboutInfo {
  app: string
  version: string
  api_docs: string
  data_dir: string | null
}

export interface TaskStats {
  scanned?: number
  parsed?: number
  skipped?: number
  added_items?: number
  added_files?: number
  updated_files?: number
  moved_files?: number
  missing?: number
  invalid?: number
  deleted_items?: number
  invalid_examples?: string[]
  total?: number
  done?: number
  scrape_total?: number
  scrape_done?: number
  ok?: number
  failed?: number
  skipped_count?: number
  failures?: { item_id: number; reason: string; errors?: string[] }[]
  scrape?: Record<string, unknown>
  error?: string
  [key: string]: unknown
}

export interface TaskInfo {
  id: number
  kind: 'scan' | 'scrape' | 'refresh' | 'image'
  library_id: number | null
  status: 'running' | 'success' | 'failed'
  message: string | null
  stats: TaskStats
  started_at: string
  finished_at: string | null
}

export interface ProviderTestResult {
  provider: string
  ok: boolean
  status: string
  message: string
  latency_ms: number
}
