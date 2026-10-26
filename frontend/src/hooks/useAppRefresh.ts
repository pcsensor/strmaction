import { useCallback, useEffect, useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { useToast } from '../store/ui'
import { t } from '../i18n/zh-CN'

interface RefreshOptions {
  showToast?: boolean
}

export function useAppRefresh() {
  const queryClient = useQueryClient()
  const toast = useToast()
  const [isRefreshing, setIsRefreshing] = useState(false)
  const refreshingRef = useRef(false)

  const refresh = useCallback(
    async (options: RefreshOptions = {}) => {
      const { showToast = true } = options
      if (refreshingRef.current) return
      refreshingRef.current = true
      setIsRefreshing(true)

      try {
        // 先失效全部缓存，再立即重新拉取当前屏幕活跃的 queries
        await queryClient.invalidateQueries()
        await queryClient.refetchQueries({ type: 'active' })

        if (showToast) {
          toast({
            title: t('toast.refreshed'),
            tone: 'success',
          })
        }
      } catch (error) {
        if (showToast) {
          toast({
            title: t('toast.refreshFailed'),
            tone: 'error',
          })
        }
      } finally {
        // 保持至少 400ms 的动画时间，让用户有清晰的刷新视觉反馈
        setTimeout(() => {
          refreshingRef.current = false
          setIsRefreshing(false)
        }, 400)
      }
    },
    [queryClient, toast],
  )

  // 监听外部派发的刷新事件（例如来自移动端原生桥接或后台通信）
  useEffect(() => {
    const handleRefreshEvent = () => {
      void refresh({ showToast: true })
    }
    window.addEventListener('strmaction:refresh', handleRefreshEvent)
    return () => {
      window.removeEventListener('strmaction:refresh', handleRefreshEvent)
    }
  }, [refresh])

  // 监听桌面端快捷键：单键 R 软刷新、F5 软刷新（原位更新，零白屏）
  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null
      if (
        target &&
        (target.tagName === 'INPUT' ||
          target.tagName === 'TEXTAREA' ||
          target.tagName === 'SELECT' ||
          target.isContentEditable)
      ) {
        return
      }

      // 单键 R / r（未按 Command / Ctrl / Alt 组合键）
      if (
        (event.key === 'r' || event.key === 'R') &&
        !event.metaKey &&
        !event.ctrlKey &&
        !event.altKey
      ) {
        event.preventDefault()
        void refresh({ showToast: true })
        return
      }

      // 拦截单个 F5，执行无白屏软刷新
      if (event.key === 'F5' && !event.ctrlKey && !event.metaKey) {
        event.preventDefault()
        void refresh({ showToast: true })
        return
      }
    }

    window.addEventListener('keydown', handleKeyDown)
    return () => {
      window.removeEventListener('keydown', handleKeyDown)
    }
  }, [refresh])

  return { refresh, isRefreshing }
}
