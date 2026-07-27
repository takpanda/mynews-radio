'use client'

import { useCallback, useEffect, useState } from 'react'
import { toast } from 'react-hot-toast'
import {
  getSubscriptionState,
  isPushSupported,
  registerPushSubscription,
  unregisterPushSubscription,
  type SubscriptionState,
} from '../lib/push-subscription'

export default function PushSubscriptionToggle() {
  const [state, setState] = useState<SubscriptionState | null>(null)
  const [loading, setLoading] = useState(false)

  const refreshState = useCallback(async () => {
    const s = await getSubscriptionState()
    setState(s)
  }, [])

  useEffect(() => {
    refreshState()
  }, [refreshState])

  const handleToggle = useCallback(async () => {
    if (loading || !state) return

    if (state.status === 'subscribed') {
      setLoading(true)
      try {
        await unregisterPushSubscription()
        await refreshState()
        toast.success('通知をオフにしました')
      } catch {
        toast.error('通知の解除に失敗しました')
      } finally {
        setLoading(false)
      }
      return
    }

    if (!isPushSupported()) return

    if (state.status === 'denied') {
      toast('ブラウザの設定で通知を有効にしてください', { icon: 'ℹ️' })
      return
    }

    setLoading(true)
    try {
      const newState = await registerPushSubscription()
      setState(newState)
      if (newState.status === 'subscribed') {
        toast.success('通知をオンにしました')
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : '通知の登録に失敗しました'
      toast.error(msg)
      await refreshState()
    } finally {
      setLoading(false)
    }
  }, [loading, state, refreshState])

  if (!state) return null

  const isOn = state.status === 'subscribed'
  const notSupported = state.status === 'unsupported'
  const isDenied = state.status === 'denied'

  if (notSupported) {
    return (
      <span className="inline-flex items-center gap-1.5 text-xs text-slate-400">
        <svg aria-hidden="true" viewBox="0 0 24 24" className="h-3.5 w-3.5" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
          <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9" />
          <path d="M13.73 21a2 2 0 0 1-3.46 0" />
        </svg>
        通知に対応していません
      </span>
    )
  }

  return (
    <button
      type="button"
      onClick={handleToggle}
      disabled={loading}
      className={`inline-flex items-center gap-2 rounded-full px-3 py-1 text-xs font-medium transition disabled:cursor-wait disabled:opacity-60 ${
        isOn
          ? 'bg-sky-100 text-sky-800 hover:bg-sky-200'
          : isDenied
            ? 'bg-slate-100 text-slate-400 cursor-not-allowed'
            : 'bg-slate-100 text-slate-600 hover:bg-slate-200'
      }`}
      aria-pressed={isOn}
      title={
        isDenied
          ? 'ブラウザの設定で通知を有効にしてください'
          : isOn
            ? '通知をオフにする'
            : '毎朝、完成を通知'
      }
    >
      <svg
        aria-hidden="true"
        viewBox="0 0 24 24"
        className={`h-3.5 w-3.5 ${isOn ? 'text-sky-600' : 'text-slate-400'}`}
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
      >
        <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9" />
        <path d="M13.73 21a2 2 0 0 1-3.46 0" />
      </svg>
      {loading ? (
        <span className="flex items-center gap-1">
          <span className="h-1 w-1 animate-pulse rounded-full bg-current" />
          処理中...
        </span>
      ) : isOn ? (
        '通知ON'
      ) : isDenied ? (
        '通知オフ'
      ) : (
        '毎朝、完成を通知'
      )}
    </button>
  )
}
