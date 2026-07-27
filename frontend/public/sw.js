self.addEventListener('install', () => self.skipWaiting())

self.addEventListener('activate', (event) => event.waitUntil(clients.claim()))

self.addEventListener('push', (event) => {
  let payload = {}
  try {
    payload = event.data?.json() ?? {}
  } catch {}

  const rawUrl = payload.url
  const url = typeof rawUrl === 'string' && (rawUrl === '/' || /^\/episodes\/\d+$/.test(rawUrl))
    ? rawUrl
    : '/'
  const episodeId = typeof rawUrl === 'string' ? rawUrl.match(/\/episodes\/(\d+)/)?.[1] : undefined
  const title = 'MyNews Radio'
  const body = payload.body ? String(payload.body) : '新しい番組が公開されました'
  const tag = `mynews-${episodeId || Date.now()}`

  event.waitUntil(
    self.registration.showNotification(title, {
      body,
      icon: '/favicon.ico',
      tag,
      data: { url, episode_id: episodeId ? Number(episodeId) : undefined },
    })
  )
})

self.addEventListener('notificationclick', (event) => {
  event.notification.close()
  const rawUrl = event.notification.data?.url
  const validUrl = typeof rawUrl === 'string' && (rawUrl === '/' || /^\/episodes\/\d+$/.test(rawUrl))
  if (!validUrl) return
  const absoluteUrl = new URL(rawUrl, self.location.origin).href
  event.waitUntil(
    clients.matchAll({ type: 'window', includeUncontrolled: true }).then((windowClients) => {
      const existing = windowClients.find((c) => c.url === absoluteUrl && 'focus' in c)
      if (existing) return existing.focus()
      return clients.openWindow(absoluteUrl)
    })
  )
})
