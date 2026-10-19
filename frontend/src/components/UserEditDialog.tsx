import { useState, useEffect } from 'react'
import { X } from 'lucide-react'
import {
  useCreateUser,
  useUpdateUser,
  useUpdateUserLibraries,
  useLibraries,
  useUser,
} from '../api/hooks'
import type { UserOut } from '../api/types'
import { LoadingBlock } from './Spinner'

interface UserEditDialogProps {
  user: UserOut | null
  onClose: () => void
}

export function UserEditDialog({ user, onClose }: UserEditDialogProps) {
  const isCreating = user === null
  const { data: userDetail, isLoading: loadingDetail } = useUser(user?.id ?? null)
  const { data: libraries } = useLibraries()
  const createUser = useCreateUser()
  const updateUser = useUpdateUser()
  const updateLibraries = useUpdateUserLibraries()

  const [username, setUsername] = useState(user?.username ?? '')
  const [password, setPassword] = useState('')
  const [displayName, setDisplayName] = useState(user?.display_name ?? '')
  const [role, setRole] = useState<'admin' | 'user'>(user?.role ?? 'user')
  const [enabled, setEnabled] = useState(user?.enabled ?? true)
  const [selectedLibraries, setSelectedLibraries] = useState<number[]>([])

  useEffect(() => {
    if (userDetail?.libraries) {
      setSelectedLibraries(userDetail.libraries.map((lib) => lib.id))
    }
  }, [userDetail])

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()

    try {
      if (isCreating) {
        // 创建用户
        await createUser.mutateAsync({
          username: username.trim(),
          password,
          display_name: displayName.trim() || undefined,
          role,
          library_ids: role === 'user' ? selectedLibraries : undefined,
        })
      } else {
        // 更新用户基本信息
        const updates: {
          password?: string
          display_name?: string
          enabled?: boolean
          role?: 'admin' | 'user'
        } = {}

        if (password) updates.password = password
        if (displayName !== user?.display_name) {
          updates.display_name = displayName.trim() || undefined
        }
        if (enabled !== user?.enabled) updates.enabled = enabled
        if (role !== user?.role) updates.role = role

        if (Object.keys(updates).length > 0) {
          await updateUser.mutateAsync({ id: user!.id, data: updates })
        }

        // 更新库授权（仅普通用户）
        if (role === 'user') {
          await updateLibraries.mutateAsync({
            id: user!.id,
            library_ids: selectedLibraries,
          })
        }
      }

      onClose()
    } catch (error: any) {
      alert(error.message || '操作失败')
    }
  }

  const toggleLibrary = (libId: number) => {
    setSelectedLibraries((prev) =>
      prev.includes(libId) ? prev.filter((id) => id !== libId) : [...prev, libId],
    )
  }

  const isPending = createUser.isPending || updateUser.isPending || updateLibraries.isPending

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
      <div className="w-full max-w-2xl rounded-xl border border-zinc-800 bg-zinc-900 shadow-2xl">
        {/* 头部 */}
        <div className="flex items-center justify-between border-b border-zinc-800 p-6">
          <h2 className="text-xl font-semibold text-white">
            {isCreating ? '新增用户' : '编辑用户'}
          </h2>
          <button
            onClick={onClose}
            className="rounded-lg p-2 text-zinc-400 transition hover:bg-zinc-800 hover:text-white"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        {/* 加载中 */}
        {!isCreating && loadingDetail ? (
          <div className="flex items-center justify-center py-16">
            <LoadingBlock />
          </div>
        ) : (
          <form onSubmit={handleSubmit}>
            <div className="max-h-[70vh] space-y-6 overflow-y-auto p-6">
              {/* 用户名 */}
              <div>
                <label className="block text-sm font-medium text-zinc-300">
                  用户名 <span className="text-red-400">*</span>
                </label>
                <input
                  type="text"
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  disabled={!isCreating}
                  required
                  minLength={3}
                  maxLength={50}
                  className="mt-2 w-full rounded-lg border border-zinc-700 bg-zinc-800 px-4 py-2 text-white placeholder-zinc-500 focus:border-blue-500 focus:outline-none disabled:cursor-not-allowed disabled:opacity-50"
                  placeholder="请输入用户名（3-50字符）"
                />
                {!isCreating && (
                  <p className="mt-1 text-xs text-zinc-500">用户名创建后不可修改</p>
                )}
              </div>

              {/* 密码 */}
              <div>
                <label className="block text-sm font-medium text-zinc-300">
                  密码 {isCreating && <span className="text-red-400">*</span>}
                </label>
                <input
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  required={isCreating}
                  minLength={8}
                  className="mt-2 w-full rounded-lg border border-zinc-700 bg-zinc-800 px-4 py-2 text-white placeholder-zinc-500 focus:border-blue-500 focus:outline-none"
                  placeholder={isCreating ? '请输入密码（至少8位）' : '留空表示不修改密码'}
                />
              </div>

              {/* 昵称 */}
              <div>
                <label className="block text-sm font-medium text-zinc-300">昵称（可选）</label>
                <input
                  type="text"
                  value={displayName}
                  onChange={(e) => setDisplayName(e.target.value)}
                  maxLength={100}
                  className="mt-2 w-full rounded-lg border border-zinc-700 bg-zinc-800 px-4 py-2 text-white placeholder-zinc-500 focus:border-blue-500 focus:outline-none"
                  placeholder="请输入昵称"
                />
              </div>

              {/* 角色 */}
              <div>
                <label className="block text-sm font-medium text-zinc-300">角色</label>
                <select
                  value={role}
                  onChange={(e) => setRole(e.target.value as 'admin' | 'user')}
                  className="mt-2 w-full rounded-lg border border-zinc-700 bg-zinc-800 px-4 py-2 text-white focus:border-blue-500 focus:outline-none"
                >
                  <option value="user">普通用户</option>
                  <option value="admin">管理员</option>
                </select>
                <p className="mt-1 text-xs text-zinc-500">
                  管理员拥有所有权限，普通用户只能访问被授权的媒体库
                </p>
              </div>

              {/* 状态（仅编辑时） */}
              {!isCreating && (
                <div>
                  <label className="flex items-center gap-3">
                    <input
                      type="checkbox"
                      checked={enabled}
                      onChange={(e) => setEnabled(e.target.checked)}
                      className="h-4 w-4 rounded border-zinc-700 bg-zinc-800 text-blue-600 focus:ring-2 focus:ring-blue-500"
                    />
                    <span className="text-sm font-medium text-zinc-300">启用该用户</span>
                  </label>
                  <p className="ml-7 mt-1 text-xs text-zinc-500">
                    禁用后该用户无法登录，所有会话将失效
                  </p>
                </div>
              )}

              {/* 媒体库授权（仅普通用户） */}
              {role === 'user' && (
                <div>
                  <label className="block text-sm font-medium text-zinc-300">
                    授权媒体库 <span className="text-red-400">*</span>
                  </label>
                  <div className="mt-3 space-y-2">
                    {libraries?.libraries.map((lib) => (
                      <label
                        key={lib.id}
                        className="flex items-center gap-3 rounded-lg border border-zinc-800 bg-zinc-800/50 p-3 transition hover:border-zinc-700 hover:bg-zinc-800"
                      >
                        <input
                          type="checkbox"
                          checked={selectedLibraries.includes(lib.id)}
                          onChange={() => toggleLibrary(lib.id)}
                          className="h-4 w-4 rounded border-zinc-700 bg-zinc-800 text-blue-600 focus:ring-2 focus:ring-blue-500"
                        />
                        <div className="flex-1">
                          <div className="text-sm font-medium text-white">{lib.name}</div>
                          <div className="text-xs text-zinc-500">
                            {lib.type === 'movie'
                              ? '电影'
                              : lib.type === 'tv'
                                ? '电视剧'
                                : lib.type === 'home'
                                  ? '家庭视频'
                                  : '课程'}
                          </div>
                        </div>
                      </label>
                    ))}
                  </div>
                  {libraries?.libraries.length === 0 && (
                    <p className="mt-2 text-sm text-zinc-500">暂无媒体库</p>
                  )}
                </div>
              )}
            </div>

            {/* 底部按钮 */}
            <div className="flex justify-end gap-3 border-t border-zinc-800 p-6">
              <button
                type="button"
                onClick={onClose}
                className="rounded-lg px-4 py-2 text-sm font-medium text-zinc-400 transition hover:bg-zinc-800"
              >
                取消
              </button>
              <button
                type="submit"
                disabled={isPending || (role === 'user' && selectedLibraries.length === 0)}
                className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white transition hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {isPending ? '保存中...' : isCreating ? '创建用户' : '保存更改'}
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  )
}
