import { create } from 'zustand'

export type ToastTone = 'default' | 'success' | 'error'

export interface Toast {
  id: number
  title: string
  description?: string
  tone?: ToastTone
  actionLabel?: string
  onAction?: () => void
  timeout?: number
}

interface UIState {
  toasts: Toast[]
  tvMode: boolean
  pushToast: (toast: Omit<Toast, 'id'>) => number
  dismissToast: (id: number) => void
  setTvMode: (value: boolean) => void
}

let toastSeq = 0

export const useUIStore = create<UIState>((set) => ({
  toasts: [],
  tvMode: false,
  pushToast: (toast) => {
    const id = ++toastSeq
    set((state) => ({
      toasts: [...state.toasts, { timeout: 3600, tone: 'default', ...toast, id }],
    }))
    return id
  },
  dismissToast: (id) =>
    set((state) => ({ toasts: state.toasts.filter((toast) => toast.id !== id) })),
  setTvMode: (value) => set({ tvMode: value }),
}))

export function useToast() {
  return useUIStore((state) => state.pushToast)
}
