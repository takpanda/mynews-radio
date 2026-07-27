'use client'

const SUBSCRIPTION_ID_KEY = 'push_subscription_id'

export interface SubscriptionState {
  status: 'unsupported' | 'denied' | 'prompt' | 'granted' | 'subscribed'
  subscriptionId: string | null
}

function urlBase64ToUint8Array(base64String: string): Uint8Array {
  const padding = '='.repeat((4 - (base64String.length % 4)) % 4)
  const base64 = (base64String + padding).replace(/-/g, '+').replace(/_/g, '/')
  const rawData = atob(base64)
  return Uint8Array.from([...rawData].map((ch) => ch.charCodeAt(0)))
}

export function isPushSupported(): boolean {
  return 'serviceWorker' in navigator && 'PushManager' in window && 'Notification' in window
}

export function getStoredSubscriptionId(): string | null {
  return localStorage.getItem(SUBSCRIPTION_ID_KEY)
}

export function clearStoredSubscriptionId(): void {
  localStorage.removeItem(SUBSCRIPTION_ID_KEY)
}

export async function getSubscriptionState(): Promise<SubscriptionState> {
  if (!isPushSupported()) return { status: 'unsupported', subscriptionId: null }

  if (Notification.permission === 'denied') {
    const staleId = getStoredSubscriptionId()
    if (staleId) {
      fetch(`/api/push/subscriptions/${encodeURIComponent(staleId)}`, { method: 'DELETE' }).catch(() => {})
      clearStoredSubscriptionId()
    }
    return { status: 'denied', subscriptionId: null }
  }

  const storedId = getStoredSubscriptionId()
  if (storedId) {
    try {
      const registration = await navigator.serviceWorker.ready
      const realSub = await registration.pushManager.getSubscription()
      if (realSub) {
        return { status: 'subscribed', subscriptionId: storedId }
      }
    } catch {
      return { status: 'subscribed', subscriptionId: storedId }
    }
    clearStoredSubscriptionId()
  }

  return { status: Notification.permission === 'granted' ? 'granted' : 'prompt', subscriptionId: null }
}

export async function registerPushSubscription(): Promise<SubscriptionState> {
  if (!isPushSupported()) return { status: 'unsupported', subscriptionId: null }

  const permission = await Notification.requestPermission()
  if (permission !== 'granted') {
    return { status: 'denied', subscriptionId: null }
  }

  const registration = await navigator.serviceWorker.ready

  const res = await fetch('/api/push/vapid-public-key')
  if (!res.ok) throw new Error('Push通知がサーバーで設定されていません')
  const { public_key: vapidKey } = await res.json()

  const pushSubscription = await registration.pushManager.subscribe({
    userVisibleOnly: true,
    applicationServerKey: urlBase64ToUint8Array(vapidKey) as BufferSource,
  })

  const subData = pushSubscription.toJSON()
  const registerRes = await fetch('/api/push/subscriptions', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      endpoint: subData.endpoint,
      keys: subData.keys,
    }),
  })

  if (!registerRes.ok) throw new Error('購読の登録に失敗しました')

  const { subscription_id } = await registerRes.json()
  localStorage.setItem(SUBSCRIPTION_ID_KEY, subscription_id)
  return { status: 'subscribed', subscriptionId: subscription_id }
}

export async function unregisterPushSubscription(): Promise<void> {
  const storedId = getStoredSubscriptionId()
  if (storedId) {
    const res = await fetch(`/api/push/subscriptions/${encodeURIComponent(storedId)}`, { method: 'DELETE' })
    if (!res.ok) {
      throw new Error('サーバーでの購読解除に失敗しました')
    }
    clearStoredSubscriptionId()
  }

  try {
    const registration = await navigator.serviceWorker.ready
    const subscription = await registration.pushManager.getSubscription()
    if (subscription) await subscription.unsubscribe()
  } catch {
  }
}
