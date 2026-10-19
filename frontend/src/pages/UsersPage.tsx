import { useState } from 'react'
import { Trash2, Plus, Edit2, Shield, User as UserIcon } from 'lucide-react'
import { useUsers, useDeleteUser, useAuthState } from '../api/hooks'
import { LoadingBlock } from '../components/Spinner'
import { UserEditDialog } from '../components/UserEditDialog'
import type { UserOut } from '../api/types'

export function UsersPage() {
  const { data: users, isLoading } = useUsers()
  const { data: authState } = useAuthState()
  const deleteUser = useDeleteUser()
  const [editingUser, setEditingUser] = useState<UserOut | null>(null)
  const [isCreating, setIsCreating] = useState(false)
  const [deleteConfirm, setDeleteConfirm] = useState<number | null>(null)

  if (isLoading) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <LoadingBlock />
      </div>
    )
  }

  const handleDelete = async (id: number) => {
    try {
      await deleteUser.mutateAsync(id)
      setDeleteConfirm(null)
    } catch (error) {
      console.error('删除用户失败:', error)
    }
  }

  return (
    <div className="mx-auto max-w-6xl px-5 pb-24 pt-28 sm:px-10">
      <div className="mb-8 flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="text-[11px] font-semibold uppercase tracking-[0.22em] text-accent/80">
            ACCESS CONTROL
          </p>
          <h1 className="mt-2 font-display text-3xl font-black tracking-tight text-white">
            用户管理
          </h1>
          <p className="mt-2 text-[13px] text-ink-400">
            管理系统用户和媒体库访问权限
          </p>
        </div>
        <button
          onClick={() => setIsCreating(true)}
          className="btn-primary gap-2 py-2 text-sm"
        >
          <Plus className="h-4 w-4" />
          新增用户
        </button>
      </div>

      <div className="overflow-hidden rounded-xl border border-zinc-800 bg-zinc-900/50">
        <table className="w-full">
          <thead>
            <tr className="border-b border-zinc-800 bg-zinc-900/80 text-left text-sm text-zinc-400">
              <th className="px-6 py-4 font-medium">用户</th>
              <th className="px-6 py-4 font-medium">角色</th>
              <th className="px-6 py-4 font-medium">状态</th>
              <th className="px-6 py-4 font-medium">授权媒体库</th>
              <th className="px-6 py-4 font-medium">最后登录</th>
              <th className="px-6 py-4 font-medium">操作</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-zinc-800">
            {users?.map((user) => (
              <tr key={user.id} className="text-sm text-zinc-300 hover:bg-zinc-800/50">
                <td className="px-6 py-4">
                  <div className="flex items-center gap-3">
                    <div className="flex h-10 w-10 items-center justify-center rounded-full bg-zinc-800">
                      {user.role === 'admin' ? (
                        <Shield className="h-5 w-5 text-amber-400" />
                      ) : (
                        <UserIcon className="h-5 w-5 text-blue-400" />
                      )}
                    </div>
                    <div>
                      <div className="font-medium text-white">{user.username}</div>
                      {user.display_name && (
                        <div className="text-xs text-zinc-500">{user.display_name}</div>
                      )}
                    </div>
                  </div>
                </td>
                <td className="px-6 py-4">
                  {user.role === 'admin' ? (
                    <span className="inline-flex items-center gap-1 rounded-full bg-amber-400/10 px-2 py-1 text-xs font-medium text-amber-400">
                      管理员
                    </span>
                  ) : (
                    <span className="inline-flex items-center gap-1 rounded-full bg-blue-400/10 px-2 py-1 text-xs font-medium text-blue-400">
                      普通用户
                    </span>
                  )}
                </td>
                <td className="px-6 py-4">
                  {user.enabled ? (
                    <span className="text-green-400">启用</span>
                  ) : (
                    <span className="text-zinc-500">禁用</span>
                  )}
                </td>
                <td className="px-6 py-4">
                  {user.role === 'admin' ? (
                    <span className="text-zinc-500">全部</span>
                  ) : user.library_count !== null ? (
                    <span>{user.library_count} 个媒体库</span>
                  ) : (
                    <span className="text-zinc-500">—</span>
                  )}
                </td>
                <td className="px-6 py-4 text-zinc-500">
                  {user.last_login_at
                    ? new Date(user.last_login_at).toLocaleString('zh-CN')
                    : '从未登录'}
                </td>
                <td className="px-6 py-4">
                  <div className="flex items-center gap-2">
                    <button
                      onClick={() => setEditingUser(user)}
                      className="rounded-lg p-2 text-zinc-400 transition hover:bg-zinc-800 hover:text-white"
                      title="编辑"
                    >
                      <Edit2 className="h-4 w-4" />
                    </button>
                    {user.id !== authState?.user?.id && (
                      <button
                        onClick={() => setDeleteConfirm(user.id)}
                        className="rounded-lg p-2 text-zinc-400 transition hover:bg-red-500/10 hover:text-red-400"
                        title="删除"
                      >
                        <Trash2 className="h-4 w-4" />
                      </button>
                    )}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>

        {!users || users.length === 0 ? (
          <div className="py-16 text-center text-zinc-500">
            暂无用户
          </div>
        ) : null}
      </div>

      {/* 新增/编辑用户对话框 */}
      {(isCreating || editingUser) && (
        <UserEditDialog
          user={editingUser}
          onClose={() => {
            setIsCreating(false)
            setEditingUser(null)
          }}
        />
      )}

      {/* 删除确认对话框 */}
      {deleteConfirm && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
          <div className="w-full max-w-md rounded-xl border border-zinc-800 bg-zinc-900 p-6">
            <h3 className="text-lg font-semibold text-white">确认删除</h3>
            <p className="mt-2 text-sm text-zinc-400">
              确定要删除该用户吗？该操作将同时删除用户的所有播放进度和会话记录，且无法恢复。
            </p>
            <div className="mt-6 flex justify-end gap-3">
              <button
                onClick={() => setDeleteConfirm(null)}
                className="rounded-lg px-4 py-2 text-sm font-medium text-zinc-400 transition hover:bg-zinc-800"
              >
                取消
              </button>
              <button
                onClick={() => handleDelete(deleteConfirm)}
                disabled={deleteUser.isPending}
                className="rounded-lg bg-red-600 px-4 py-2 text-sm font-medium text-white transition hover:bg-red-700 disabled:opacity-50"
              >
                {deleteUser.isPending ? '删除中...' : '确认删除'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
