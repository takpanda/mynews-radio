import {
  isPushSupported,
  getSubscriptionState,
  registerPushSubscription,
  unregisterPushSubscription,
} from '../push-subscription'

function setupPushGlobals() {
  if (typeof globalThis.PushManager === 'undefined') {
    Object.defineProperty(globalThis, 'PushManager', {
      value: {},
      writable: true,
      configurable: true,
    })
  }
  if (!('serviceWorker' in navigator)) {
    Object.defineProperty(navigator, 'serviceWorker', {
      value: { register: jest.fn().mockResolvedValue({}) } as unknown as ServiceWorkerContainer,
      writable: true,
      configurable: true,
    })
  }
  if (typeof globalThis.Notification === 'undefined') {
    Object.defineProperty(globalThis, 'Notification', {
      value: { permission: 'default', requestPermission: jest.fn() },
      writable: true,
      configurable: true,
    })
  }
}

function mockNotification(permission: NotificationPermission, requestResult?: NotificationPermission) {
  const mock = {
    permission,
    requestPermission: jest.fn().mockResolvedValue(requestResult ?? permission),
  }
  Object.defineProperty(globalThis, 'Notification', {
    value: mock,
    writable: true,
    configurable: true,
  })
}

const VAPID_PUBLIC_KEY = 'BOSJ-ss6wHrmOBgodHoFvQiHEbzsLDtZOlx8JsYN-args7UOapiq-hWwrKQf8-nzDF35z7d2dfc5ruBswc1gq70'

beforeEach(() => {
  localStorage.clear()
  jest.restoreAllMocks()
  setupPushGlobals()
})

describe('isPushSupported', () => {
  it('returns false when PushManager is missing', () => {
    // @ts-expect-error - testing removal
    delete globalThis.PushManager
    expect(isPushSupported()).toBe(false)
  })

  it('returns false when Notification is missing', () => {
    // @ts-expect-error - testing removal
    delete globalThis.Notification
    expect(isPushSupported()).toBe(false)
  })

  it('returns true when PushManager, serviceWorker, and Notification exist', () => {
    expect(isPushSupported()).toBe(true)
  })
})

describe('getSubscriptionState', () => {
  it('returns unsupported when PushManager is missing', async () => {
    // @ts-expect-error - testing removal
    delete globalThis.PushManager
    const state = await getSubscriptionState()
    expect(state.status).toBe('unsupported')
  })

  it('returns denied when permission is denied', async () => {
    mockNotification('denied')
    const state = await getSubscriptionState()
    expect(state.status).toBe('denied')
  })

  it('clears stale ID when DELETE succeeds (denied)', async () => {
    localStorage.setItem('push_subscription_id', 'stale-denied-id')
    mockNotification('denied')
    global.fetch = jest.fn().mockResolvedValue({ ok: true, status: 204 })

    const state = await getSubscriptionState()

    expect(state.status).toBe('denied')
    expect(state.subscriptionId).toBeNull()
    expect(localStorage.getItem('push_subscription_id')).toBeNull()
    expect(global.fetch).toHaveBeenCalledWith(
      '/api/push/subscriptions/stale-denied-id',
      expect.objectContaining({ method: 'DELETE' }),
    )
  })

  it('preserves stale ID when DELETE returns HTTP error (denied)', async () => {
    localStorage.setItem('push_subscription_id', 'stale-denied-id')
    mockNotification('denied')
    global.fetch = jest.fn().mockResolvedValue({ ok: false, status: 500 })

    const state = await getSubscriptionState()

    expect(state.status).toBe('denied')
    expect(state.subscriptionId).toBeNull()
    expect(localStorage.getItem('push_subscription_id')).toBe('stale-denied-id')
  })

  it('preserves stale ID when DELETE fails with network error (denied)', async () => {
    localStorage.setItem('push_subscription_id', 'stale-denied-id')
    mockNotification('denied')
    global.fetch = jest.fn().mockRejectedValue(new Error('Network error'))

    const state = await getSubscriptionState()

    expect(state.status).toBe('denied')
    expect(state.subscriptionId).toBeNull()
    expect(localStorage.getItem('push_subscription_id')).toBe('stale-denied-id')
  })

  it('returns subscribed when stored ID exists and real subscription is active', async () => {
    localStorage.setItem('push_subscription_id', 'test-id-123')
    mockNotification('granted')

    const mockRegistration = {
      pushManager: {
        getSubscription: jest.fn().mockResolvedValue({ endpoint: 'https://test.com/sub' }),
      },
    }
    Object.defineProperty(navigator, 'serviceWorker', {
      value: { ready: Promise.resolve(mockRegistration), register: jest.fn() } as unknown as ServiceWorkerContainer,
      writable: true,
      configurable: true,
    })

    const state = await getSubscriptionState()
    expect(state.status).toBe('subscribed')
    expect(state.subscriptionId).toBe('test-id-123')
  })

  it('clears stale stored ID when real subscription is gone', async () => {
    localStorage.setItem('push_subscription_id', 'stale-id')
    mockNotification('granted')

    const mockRegistration = {
      pushManager: {
        getSubscription: jest.fn().mockResolvedValue(null),
      },
    }
    Object.defineProperty(navigator, 'serviceWorker', {
      value: { ready: Promise.resolve(mockRegistration), register: jest.fn() } as unknown as ServiceWorkerContainer,
      writable: true,
      configurable: true,
    })

    const state = await getSubscriptionState()
    expect(state.status).toBe('granted')
    expect(state.subscriptionId).toBeNull()
    expect(localStorage.getItem('push_subscription_id')).toBeNull()
  })

  it('returns prompt when no stored ID and permission is default', async () => {
    mockNotification('default')
    const state = await getSubscriptionState()
    expect(state.status).toBe('prompt')
  })
})

describe('registerPushSubscription', () => {
  beforeEach(() => {
    mockNotification('default', 'granted')
    const mockRegistration = {
      pushManager: {
        subscribe: jest.fn().mockResolvedValue({
          toJSON: () => ({
            endpoint: 'https://push.example.com/abc',
            keys: { p256dh: 'key123', auth: 'auth456' },
          }),
        }),
      },
    }
    Object.defineProperty(navigator, 'serviceWorker', {
      value: { ready: Promise.resolve(mockRegistration), register: jest.fn() } as unknown as ServiceWorkerContainer,
      writable: true,
      configurable: true,
    })
  })

  it('returns denied when permission is not granted', async () => {
    mockNotification('denied')
    const state = await registerPushSubscription()
    expect(state.status).toBe('denied')
  })

  it('throws when VAPID key endpoint fails', async () => {
    global.fetch = jest.fn().mockResolvedValueOnce({ ok: false, status: 503 })
    await expect(registerPushSubscription()).rejects.toThrow()
  })

  it('registers and stores subscription ID', async () => {
    global.fetch = jest.fn()
      .mockResolvedValueOnce({ ok: true, json: async () => ({ public_key: VAPID_PUBLIC_KEY }) })
      .mockResolvedValueOnce({ ok: true, json: async () => ({ subscription_id: 'sub-id-456' }) })

    const state = await registerPushSubscription()
    expect(state.status).toBe('subscribed')
    expect(state.subscriptionId).toBe('sub-id-456')
    expect(localStorage.getItem('push_subscription_id')).toBe('sub-id-456')
  })
})

describe('unregisterPushSubscription', () => {
  const setupMockReg = (withSub = true) => {
    const mockSubscription = withSub ? { unsubscribe: jest.fn().mockResolvedValue(undefined) } : null
    const mockRegistration = {
      pushManager: {
        getSubscription: jest.fn().mockResolvedValue(mockSubscription),
      },
    }
    Object.defineProperty(navigator, 'serviceWorker', {
      value: { ready: Promise.resolve(mockRegistration), register: jest.fn() } as unknown as ServiceWorkerContainer,
      writable: true,
      configurable: true,
    })
  }

  it('removes stored ID on successful DELETE (204) and unsubscribes from pushManager', async () => {
    localStorage.setItem('push_subscription_id', 'test-id')
    global.fetch = jest.fn().mockResolvedValue({ ok: true, status: 204 })
    setupMockReg(true)

    await unregisterPushSubscription()

    expect(localStorage.getItem('push_subscription_id')).toBeNull()
  })

  it('keeps stored ID when DELETE returns HTTP error (500)', async () => {
    localStorage.setItem('push_subscription_id', 'test-id')
    global.fetch = jest.fn().mockResolvedValue({ ok: false, status: 500 })

    await expect(unregisterPushSubscription()).rejects.toThrow('サーバーでの購読解除に失敗しました')
    expect(localStorage.getItem('push_subscription_id')).toBe('test-id')
  })

  it('keeps stored ID when DELETE returns HTTP error (429)', async () => {
    localStorage.setItem('push_subscription_id', 'test-id')
    global.fetch = jest.fn().mockResolvedValue({ ok: false, status: 429 })

    await expect(unregisterPushSubscription()).rejects.toThrow('サーバーでの購読解除に失敗しました')
    expect(localStorage.getItem('push_subscription_id')).toBe('test-id')
  })

  it('keeps stored ID when network fails (fetch throws)', async () => {
    localStorage.setItem('push_subscription_id', 'test-id')
    global.fetch = jest.fn().mockRejectedValue(new Error('Network error'))

    await expect(unregisterPushSubscription()).rejects.toThrow('Network error')
    expect(localStorage.getItem('push_subscription_id')).toBe('test-id')
  })

  it('handles cleanup when no stored ID', async () => {
    await unregisterPushSubscription()
    expect(localStorage.getItem('push_subscription_id')).toBeNull()
  })
})
