import { useCallback } from 'react'
import { usePlay } from '../api/hooks'
import { useToast } from '../store/ui'
import { t } from '../i18n/zh-CN'
import { copyText } from '../utils/clipboard'
import type { PlayResponse } from '../api/types'

interface StartOptions {
  /** builtin（默认）/ external（外部 mpv）/ auto / copy */
  mode?: string
  mediaFileId?: number
  silent?: boolean
}

export function useStartPlayback() {
  const play = usePlay()
  const toast = useToast()

  return useCallback(
    async (itemId: number, options: StartOptions = {}): Promise<PlayResponse | null> => {
      const bridge =
        typeof window !== 'undefined' ? window.StrmActionNative : undefined
      const nativeMode =
        options.mode === 'external' || options.mode === 'external_mpv'

      // 伴侣 App：原生层自己请求 /api/play，网页不接触 URL 与 token（§12.8）
      if (bridge?.play) {
        try {
          if (nativeMode && bridge.playExternal) {
            bridge.playExternal(itemId)
          } else {
            bridge.play(itemId)
          }
          return null
        } catch (error) {
          toast({
            title: t('player.failed'),
            description: (error as Error).message || t('player.failed'),
            tone: 'error',
          })
          return null
        }
      }

      try {
        const result = await play.mutateAsync({
          itemId,
          mode: options.mode,
          mediaFileId: options.mediaFileId,
        })

        const copy = async () => {
          const ok = await copyText(result.play_url)
          toast({
            title: ok ? t('player.copyTitle') : t('toast.copyFailed'),
            description: ok ? t('player.copyTip') : result.play_url,
            tone: ok ? 'success' : 'error',
            timeout: 7000,
          })
        }

        if (result.mode === 'browser_intent' && result.action) {
          toast({
            title: t('player.intent'),
            description: t('player.intentTip'),
            actionLabel: t('player.copyAction'),
            onAction: copy,
            timeout: 8000,
          })
          window.location.href = result.action
        } else if (result.mode === 'copy') {
          await copy()
        } else if (result.mode === 'desktop_mpv') {
          toast({
            title: t('player.backend'),
            description: t('player.backendTip'),
            tone: 'success',
          })
        } else {
          // builtin / external_mpv 只可能出现在伴侣 App 中；浏览器拿不到原生播放器
          toast({
            title: t('player.backend'),
            description: t('player.externalHint'),
            tone: 'success',
          })
        }
        return result
      } catch (error) {
        const message = (error as Error).message || t('player.failed')
        toast({ title: t('player.failed'), description: message, tone: 'error' })
        return null
      }
    },
    [play, toast],
  )
}
