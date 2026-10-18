export interface StrmActionNativeBridge {
  /** 内置 Media3 播放器（v0.8 默认路径） */
  play?: (itemId: number) => void
  /** 外部 mpv 兜底 */
  playExternal?: (itemId: number) => void
  /** 打开伴侣 App 的服务器设置 */
  openSettings?: () => void
  isCompanion?: () => boolean
  isTV?: () => boolean
  version?: () => string
  serverHost?: () => string
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
