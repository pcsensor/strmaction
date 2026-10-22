import { useCallback } from 'react'
import { usePlay } from '../api/hooks'
import { useToast } from '../store/ui'
import { t } from '../i18n/zh-CN'
import { copyText } from '../utils/clipboard'
import type { PlayResponse } from '../api/types'

interface StartOptions {
  /** auto / builtin / browser_intent / copy */
  mode?: string
  mediaFileId?: number
  silent?: boolean
}

function downgradeCopyText(reason: PlayResponse['downgrade_reason']): {
  title: string
  description: string
} {
  switch (reason) {
    case 'requires_companion':
      return {
        title: t('player.companionOnlyTitle'),
        description: t('player.companionOnlyTip'),
      }
    case 'requires_android':
      return {
        title: t('player.intentOnlyTitle'),
        description: t('player.intentOnlyTip'),
      }
    default:
      return { title: t('player.copyTitle'), description: t('player.copyTip') }
  }
}

export function useStartPlayback() {
  const play = usePlay()
  const toast = useToast()

  return useCallback(
    async (itemId: number, options: StartOptions = {}): Promise<PlayResponse | null> => {
      const bridge =
        typeof window !== 'undefined' ? window.StrmActionNative : undefined

      // 桌面端：网页负责取播放数据（direct），Python 负责本机内嵌播放
      if (bridge?.isDesktop?.()) {
        try {
          const result = await play.mutateAsync({
            itemId,
            mode: 'direct',
            mediaFileId: options.mediaFileId,
          })
          if (!bridge.playItem) {
            throw new Error(t('player.desktopBridgeMissing'))
          }
          const reply = await bridge.playItem(JSON.stringify(result))
          if (reply && typeof reply === 'object' && 'ok' in reply && !reply.ok) {
            throw new Error(reply.error || t('player.failed'))
          }
          toast({
            title: t('player.desktop'),
            description: t('player.desktopTip'),
            tone: 'success',
          })
          return result
        } catch (error) {
          toast({
            title: t('player.failed'),
            description: (error as Error).message || t('player.failed'),
            tone: 'error',
          })
          return null
        }
      }

      // 伴侣 App：原生层自己请求 /api/play，网页不接触 URL 与 token（§12.8）
      if (bridge?.play) {
        try {
          bridge.play(itemId)
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

        const copy = async (
          title = t('player.copyTitle'),
          description = t('player.copyTip'),
        ) => {
          const ok = await copyText(result.play_url)
          toast({
            title: ok ? title : t('toast.copyFailed'),
            description: ok ? description : result.play_url,
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
          if (result.downgraded) {
            const message = downgradeCopyText(result.downgrade_reason)
            await copy(message.title, message.description)
          } else {
            await copy()
          }
        } else {
          // builtin 只可能出现在伴侣 App 中；浏览器拿不到原生播放器
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
