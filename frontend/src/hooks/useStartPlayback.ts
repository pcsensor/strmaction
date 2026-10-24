import { useCallback } from 'react'
import { usePlay } from '../api/hooks'
import { useToast } from '../store/ui'
import { t } from '../i18n/zh-CN'
import { copyText } from '../utils/clipboard'
import type { PlayMode, PlayResponse } from '../api/types'

interface StartOptions {
  mode?: PlayMode
  mediaFileId?: number
  silent?: boolean
}

export function useStartPlayback() {
  const play = usePlay()
  const toast = useToast()
  return useCallback(async (itemId: number, options: StartOptions = {}): Promise<PlayResponse | null> => {
    const bridge = window.StrmActionNative
    try {
      const request = JSON.stringify({ itemId, mediaFileId: options.mediaFileId, mode: options.mode })
      if (bridge?.requestPlayback) {
        const reply = await bridge.requestPlayback(request)
        if (reply && !reply.ok) throw new Error(reply.error || t('player.failed'))
        return null
      }
      if (bridge?.playV2) {
        bridge.playV2(request)
        return null
      }
      if (bridge?.play && options.mode !== 'copy') {
        bridge.play(itemId)
        return null
      }
      const result = await play.mutateAsync({ itemId, mode: options.mode, mediaFileId: options.mediaFileId })
      if (result.mode === 'copy') {
        const ok = await copyText(result.play_url)
        toast({
          title: ok ? t('player.copyTitle') : t('toast.copyFailed'),
          description: ok
            ? result.downgraded ? '内部播放需要使用 StrmAction App，已复制所选版本的链接。' : '已复制所选版本的播放链接。'
            : result.play_url,
          tone: ok ? 'success' : 'error',
        })
      } else if (bridge?.playItem) {
        const reply = await bridge.playItem(JSON.stringify(result))
        if (reply && !reply.ok) throw new Error(reply.error || t('player.failed'))
      } else {
        throw new Error('内部播放需要使用 StrmAction App。')
      }
      return result
    } catch (error) {
      toast({ title: t('player.failed'), description: (error as Error).message, tone: 'error' })
      return null
    }
  }, [play, toast])
}
