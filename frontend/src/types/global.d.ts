export interface StrmActionNativeBridge {
  /** 内置 Media3 播放器（v0.8 默认路径） */
  play?: (itemId: number) => void
  /** 外部 mpv 兜底 */
  playExternal?: (itemId: number) => void
  /** 打开伴侣 App 的服务器设置 / 桌面端设置 */
  openSettings?: () => void
  isCompanion?: () => boolean
  isTV?: () => boolean
  version?: () => string
  serverHost?: () => string
  /** v1.2 桌面端：WebView 壳 + 本机 mpv */
  isDesktop?: () => boolean
  playItem?: (
    payload: string,
  ) =>
    | Promise<{ ok: boolean; error?: string } | void>
    | { ok: boolean; error?: string }
    | void
  stopPlayback?: () => void
  quit?: () => void
}

declare global {
  interface Window {
    StrmActionNative?: StrmActionNativeBridge
    StrmActionReport?: (
      itemId: number,
      positionMs: number,
      durationMs: number,
      finished: boolean,
    ) => void
    StrmActionNextEpisode?: (itemId: number, finished: boolean) => void
    StrmActionRefresh?: () => void
  }
}

export {}
