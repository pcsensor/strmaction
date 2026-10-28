import { useEffect, useRef } from 'react'
import {
  useMutation,
  useQuery,
  useQueryClient,
  keepPreviousData,
} from '@tanstack/react-query'
import { api, buildQuery } from './client'
import type {
  AboutInfo,
  AppSettings,
  AuthState,
  Candidate,
  HomeData,
  ItemDetailResponse,
  ItemListResponse,
  ItemSummary,
  LibraryInfo,
  MyPlayerResponse,
  PlayResponse,
  PlayerPreference,
  ProviderTestResult,
  SearchResponse,
  SettingsResponse,
  TaskInfo,
  UserOut,
  UserDetail,
  UserCreateInput,
  UserPatchInput,
} from './types'

export const keys = {
  auth: ['auth'] as const,
  home: ['home'] as const,
  item: (id: number) => ['item', id] as const,
  items: (params: Record<string, unknown>) => ['items', params] as const,
  search: (q: string, genre?: string) => ['search', q, genre] as const,
  libraries: ['libraries'] as const,
  tasks: ['tasks'] as const,
  settings: ['settings'] as const,
  myPlayer: ['me', 'player'] as const,
  about: ['about'] as const,
  candidates: (id: number, q: string, provider: string) =>
    ['candidates', id, q, provider] as const,
  users: ['users'] as const,
  user: (id: number) => ['user', id] as const,
}

export function useAuthState() {
  return useQuery({
    queryKey: keys.auth,
    queryFn: () => api.get<AuthState>('/api/auth/state'),
    staleTime: 10_000,
  })
}

export function useLogin() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: { username: string; password: string }) =>
      api.post('/api/auth/login', body),
    onSuccess: () => {
      queryClient.invalidateQueries()
    },
  })
}

export function useSetup() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: { password: string; username?: string }) =>
      api.post('/api/auth/setup', body),
    onSuccess: () => queryClient.invalidateQueries(),
  })
}

export function useLogout() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => api.post('/api/auth/logout'),
    onSuccess: () => {
      queryClient.clear()
      window.location.assign('/')
    },
  })
}

export function useChangePassword() {
  return useMutation({
    mutationFn: (body: { current_password: string; new_password: string }) =>
      api.post('/api/auth/password', body),
  })
}

export function useHome() {
  return useQuery({
    queryKey: keys.home,
    queryFn: () => api.get<HomeData>('/api/home'),
  })
}

export function useItem(id: number | null) {
  return useQuery({
    queryKey: keys.item(id ?? 0),
    queryFn: () => api.get<ItemDetailResponse>(`/api/items/${id}`),
    enabled: id !== null && Number.isFinite(id) && id > 0,
    refetchInterval: (query) => query.state.data?.image_status?.pending ? 1500 : false,
  })
}

export function useItems(params: {
  library_id?: number
  parent_id?: string
  kind?: string
  q?: string
  genre?: string
  year?: number
  sort?: string
  page?: number
  page_size?: number
  match_state?: string
}) {
  return useQuery({
    queryKey: keys.items(params),
    queryFn: () => api.get<ItemListResponse>(`/api/items${buildQuery(params)}`),
    placeholderData: keepPreviousData,
  })
}

export function useSearch(q: string, genre?: string) {
  return useQuery({
    queryKey: keys.search(q, genre),
    queryFn: () =>
      api.get<SearchResponse>(`/api/search${buildQuery({ q, genre, limit: 100 })}`),
    enabled: true,
  })
}

export function useLibraries(enabled = true) {
  return useQuery({
    queryKey: keys.libraries,
    queryFn: () => api.get<{ libraries: LibraryInfo[] }>('/api/libraries'),
    enabled,
  })
}

export function useCreateLibrary() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      api.post<LibraryInfo>('/api/libraries', body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: keys.libraries })
    },
  })
}

export function useUpdateLibrary() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ id, body }: { id: number; body: Record<string, unknown> }) =>
      api.patch<LibraryInfo>(`/api/libraries/${id}`, body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: keys.libraries })
    },
  })
}

export function useDeleteLibrary() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => api.delete(`/api/libraries/${id}`),
    onSuccess: () => {
      queryClient.invalidateQueries()
    },
  })
}

export function useLibraryTask() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ id, action }: { id: number; action: 'scan' | 'scrape' | 'refresh' }) =>
      api.post<{ task_id: number }>(`/api/libraries/${id}/${action}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: keys.tasks })
    },
  })
}

export function useTasks(enabled = true) {
  return useQuery({
    queryKey: keys.tasks,
    queryFn: () => api.get<{ tasks: TaskInfo[] }>('/api/tasks?limit=80'),
    enabled,
    refetchInterval: (query) => {
      const data = query.state.data
      return data?.tasks?.some((task) => task.status === 'running') ? 1500 : false
    },
  })
}

export function useTaskUpdates() {
  const auth = useAuthState()
  const tasks = useTasks(auth.data?.user?.role === 'admin')
  const queryClient = useQueryClient()
  const completed = tasks.data?.tasks
    .filter((task) => task.status !== 'running')
    .map((task) => `${task.id}:${task.finished_at}`)
    .join('|')
  const previous = useRef('')
  useEffect(() => {
    if (completed === undefined || completed === previous.current) return
    previous.current = completed
    for (const queryKey of [['item'], ['items'], keys.home, keys.libraries, ['search']]) {
      void queryClient.invalidateQueries({ queryKey })
    }
  }, [completed, queryClient])
}

export function useTask(id: number | null) {
  return useQuery({
    queryKey: ['task', id],
    queryFn: () => api.get<TaskInfo>(`/api/tasks/${id}`),
    enabled: id !== null,
    refetchInterval: (query) =>
      query.state.data?.status === 'running' ? 1500 : false,
  })
}

export function useSettings(enabled = true) {
  return useQuery({
    queryKey: keys.settings,
    queryFn: () => api.get<SettingsResponse>('/api/settings'),
    enabled,
  })
}

export function usePatchSettings() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (patch: Partial<AppSettings> | Record<string, unknown>) =>
      api.patch<SettingsResponse>('/api/settings', patch),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: keys.settings })
      queryClient.invalidateQueries({ queryKey: keys.home })
    },
  })
}

export function useProviderTest() {
  return useMutation({
    mutationFn: (provider: 'tmdb' | 'tvdb') =>
      api.post<ProviderTestResult>('/api/settings/provider-test', { provider }),
  })
}

/** v1.2 当前用户的播放偏好（mode / fallback_on_error）。 */
export function useMyPlayer() {
  return useQuery({
    queryKey: keys.myPlayer,
    queryFn: () => api.get<MyPlayerResponse>('/api/me/player'),
  })
}

export function usePatchMyPlayer() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (patch: Partial<PlayerPreference>) =>
      api.patch<MyPlayerResponse>('/api/me/player', patch),
    onSuccess: (data) => {
      queryClient.setQueryData(keys.myPlayer, data)
    },
  })
}

/** 所有登录用户可见的应用信息；data_dir 仅管理员有值。 */
export function useAbout() {
  return useQuery({
    queryKey: keys.about,
    queryFn: () => api.get<AboutInfo>('/api/about'),
    staleTime: 60_000,
  })
}

export function usePlay() {
  return useMutation({
    mutationFn: ({
      itemId,
      mode,
      mediaFileId,
    }: {
      itemId: number
      mode?: string
      mediaFileId?: number
    }) =>
      api.post<PlayResponse>(`/api/play/${itemId}`, {
        mode,
        media_file_id: mediaFileId,
      }),
  })
}

export function useReportProgress() {
  return useMutation({
    mutationFn: ({
      itemId,
      positionMs,
      durationMs,
      finished,
    }: {
      itemId: number
      positionMs: number
      durationMs?: number | null
      finished?: boolean
    }) =>
      api.post(`/api/items/${itemId}/progress`, {
        position_ms: positionMs,
        duration_ms: durationMs ?? undefined,
        finished: finished ?? false,
      }),
  })
}

export function useMarkWatched() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ itemId, finished }: { itemId: number; finished: boolean }) =>
      api.post<{ count: number }>(`/api/items/${itemId}/watched`, { finished }),
    onSuccess: (_data, variables) => {
      queryClient.invalidateQueries({ queryKey: keys.item(variables.itemId) })
      queryClient.invalidateQueries({ queryKey: keys.home })
    },
  })
}

export function usePatchItem() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ id, body }: { id: number; body: Record<string, unknown> }) =>
      api.patch<ItemSummary>(`/api/items/${id}`, body),
    onSuccess: (_data, variables) => {
      queryClient.invalidateQueries({ queryKey: keys.item(variables.id) })
      queryClient.invalidateQueries({ queryKey: keys.home })
    },
  })
}

export function useRefreshItem() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: number) =>
      api.post<{ task_id: number }>(`/api/items/${id}/refresh`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: keys.tasks }),
  })
}

export function useCandidates(
  itemId: number | null,
  q: string,
  provider: string,
  enabled: boolean,
) {
  return useQuery({
    queryKey: keys.candidates(itemId ?? 0, q, provider),
    queryFn: () =>
      api.get<{ candidates: Candidate[] }>(
        `/api/items/${itemId}/match-candidates${buildQuery({ q, provider })}`,
      ),
    enabled: enabled && itemId !== null,
    staleTime: 60_000,
  })
}

export function useMatchItem() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({
      id,
      provider,
      providerId,
    }: {
      id: number
      provider: string
      providerId: string
    }) =>
      api.post(`/api/items/${id}/match`, {
        provider,
        provider_id: providerId,
      }),
    onSuccess: (_data, variables) => {
      queryClient.invalidateQueries({ queryKey: keys.item(variables.id) })
      queryClient.invalidateQueries({ queryKey: keys.home })
    },
  })
}

export function useUnmatchItem() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => api.post(`/api/items/${id}/unmatch`),
    onSuccess: (_data, id) => {
      queryClient.invalidateQueries({ queryKey: keys.item(id) })
    },
  })
}

export function useUnlockItem() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => api.post(`/api/items/${id}/unlock`),
    onSuccess: (_data, id) => {
      queryClient.invalidateQueries({ queryKey: keys.item(id) })
    },
  })
}

export function useDismissContinue() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => api.delete<{ ok: boolean }>(`/api/items/${id}/continue`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: keys.home })
    },
  })
}

export function useUploadPoster() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({
      id,
      file,
      kind,
    }: {
      id: number
      file: File
      kind: 'poster' | 'backdrop'
    }) => {
      const form = new FormData()
      form.set('file', file)
      form.set('kind', kind)
      return api.upload<{ ok: boolean; url: string }>(`/api/items/${id}/poster`, form)
    },
    onSuccess: (_data, variables) => {
      queryClient.invalidateQueries({ queryKey: keys.item(variables.id) })
      queryClient.invalidateQueries({ queryKey: keys.home })
    },
  })
}

export function useExportData() {
  return useMutation({
    mutationFn: () => api.get<Record<string, unknown>>('/api/export'),
  })
}

export function useImportData() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (data: Record<string, unknown>) =>
      api.post<{ ok: boolean; imported: Record<string, number | boolean> }>(
        '/api/import',
        { data, settings: false },
      ),
    onSuccess: () => queryClient.invalidateQueries(),
  })
}

export function useSearchLibraries() {
  return useLibraries()
}

// v0.9 用户管理
export function useUsers() {
  return useQuery({
    queryKey: keys.users,
    queryFn: () => api.get<UserOut[]>('/api/users'),
  })
}

export function useUser(id: number | null) {
  return useQuery({
    queryKey: keys.user(id ?? 0),
    queryFn: () => api.get<UserDetail>(`/api/users/${id}`),
    enabled: id !== null && Number.isFinite(id) && id > 0,
  })
}

export function useCreateUser() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (input: UserCreateInput) =>
      api.post<UserOut>('/api/users', input),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: keys.users })
    },
  })
}

export function useUpdateUser() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ id, data }: { id: number; data: UserPatchInput }) =>
      api.patch<UserOut>(`/api/users/${id}`, data),
    onSuccess: (_data, variables) => {
      queryClient.invalidateQueries({ queryKey: keys.users })
      queryClient.invalidateQueries({ queryKey: keys.user(variables.id) })
    },
  })
}

export function useDeleteUser() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => api.delete(`/api/users/${id}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: keys.users })
    },
  })
}

export function useUpdateUserLibraries() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ id, library_ids }: { id: number; library_ids: number[] }) =>
      api.put<{ user_id: number; library_count: number }>(
        `/api/users/${id}/libraries`,
        { library_ids },
      ),
    onSuccess: (_data, variables) => {
      queryClient.invalidateQueries({ queryKey: keys.users })
      queryClient.invalidateQueries({ queryKey: keys.user(variables.id) })
    },
  })
}

