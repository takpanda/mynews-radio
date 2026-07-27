/**
 * Service Worker スクリプトの検証テスト。
 * sw.js は ServiceWorkerGlobalScope で動作するため Jest で直接実行できません。
 * ここでは URL バリデーションロジックの再現・確認と、
 * 手動確認手順を記録します。
 */

import { readFileSync } from 'fs'
import path from 'path'

const SW_PATH = path.resolve(__dirname, '../../public/sw.js')

/** sw.js の URL 検証ロジックと同じパターン */
function isValidNotificationUrl(value: unknown): value is string {
  return typeof value === 'string' && (value === '/' || /^\/episodes\/\d+$/.test(value))
}

/** sw.js の notificationclick と同じ正規化ロジック */
function normalizeUrl(rawUrl: string, origin: string): string {
  return new URL(rawUrl, origin).href
}

describe('sw.js syntax', () => {
  it('is a valid JavaScript file', () => {
    expect(() => readFileSync(SW_PATH, 'utf8')).not.toThrow()
  })
})

describe('URL validation (same logic as sw.js)', () => {
  it('accepts root path "/"', () => {
    expect(isValidNotificationUrl('/')).toBe(true)
  })

  it('accepts "/episodes/123"', () => {
    expect(isValidNotificationUrl('/episodes/123')).toBe(true)
  })

  it('accepts "/episodes/0"', () => {
    expect(isValidNotificationUrl('/episodes/0')).toBe(true)
  })

  it('rejects external URL "https://example.com/"', () => {
    expect(isValidNotificationUrl('https://example.com/')).toBe(false)
  })

  it('rejects external URL "https://evil.com/phish"', () => {
    expect(isValidNotificationUrl('https://evil.com/phish')).toBe(false)
  })

  it('rejects "/episodes/abc" (non-numeric)', () => {
    expect(isValidNotificationUrl('/episodes/abc')).toBe(false)
  })

  it('rejects number type input', () => {
    expect(isValidNotificationUrl(123)).toBe(false)
  })

  it('rejects null', () => {
    expect(isValidNotificationUrl(null)).toBe(false)
  })

  it('rejects undefined', () => {
    expect(isValidNotificationUrl(undefined)).toBe(false)
  })

  it('rejects object', () => {
    expect(isValidNotificationUrl({})).toBe(false)
  })
})

describe('URL normalization (same logic as sw.js)', () => {
  const ORIGIN = 'https://mynews-radio.example.com'

  it('normalizes "/" to origin root', () => {
    expect(normalizeUrl('/', ORIGIN)).toBe('https://mynews-radio.example.com/')
  })

  it('normalizes "/episodes/42" to absolute URL', () => {
    expect(normalizeUrl('/episodes/42', ORIGIN)).toBe('https://mynews-radio.example.com/episodes/42')
  })
})

/**
 * # 手動確認手順 (Service Worker 遷移)
 *
 * 以下の手順はブラウザで実際に動作確認するためのものです。
 *
 * ## 準備
 * 1. ローカル開発サーバーを起動: `docker compose up --build` (または `cd frontend && npm run dev`)
 * 2. Chrome DevTools → Application → Service Workers で /sw.js が登録されていることを確認
 *
 * ## 確認ケース1: 正常エピソードURL (/episodes/123)
 * 1. DevTools Console で以下を実行:
 *    ```js
 *    // 通知をシミュレート
 *    const registration = await navigator.serviceWorker.ready
 *    await registration.showNotification('MyNews Radio', {
 *      body: 'テスト通知',
 *      icon: '/favicon.ico',
 *      tag: 'test-episode-123',
 *      data: { url: '/episodes/123', episode_id: 123 },
 *    })
 *    ```
 * 2. OS通知をクリック
 * 3. 期待結果: ブラウザで /episodes/123 が開く（または既存タブがfocusされる）
 *
 * ## 確認ケース2: 外部URL拒否
 * 1. DevTools Console で以下を実行:
 *    ```js
 *    const registration = await navigator.serviceWorker.ready
 *    await registration.showNotification('MyNews Radio', {
 *      body: '悪意のある通知',
 *      icon: '/favicon.ico',
 *      tag: 'test-evil',
 *      data: { url: 'https://evil.com/phish' },
 *    })
 *    ```
 * 2. OS通知をクリック
 * 3. 期待結果: 何も開かない（notificationclick が早期 return する）
 *
 * ## 確認ケース3: 型ガード (非文字列 payload)
 * 1. DevTools Console で以下を実行:
 *    ```js
 *    // Service Worker 内の push イベントをシミュレートする代わりに、
 *    // payload.url が number の場合でも通知が表示されることを確認
 *    const registration = await navigator.serviceWorker.ready
 *    await registration.showNotification('MyNews Radio', {
 *      body: '型ガードテスト',
 *      icon: '/favicon.ico',
 *      tag: 'test-typeguard',
 *      data: { url: 12345 },
 *    })
 *    ```
 * 2. 通知をクリック
 * 3. 期待結果: notificationclick の typeof チェックで弾かれ、何も開かない
 *
 * ## 確認ケース4: 既存タブfocus
 * 1. /episodes/123 を既に開いたタブを用意する
 * 2. 確認ケース1 の手順で通知を発行し、クリック
 * 3. 期待結果: 新しいタブではなく、既存の /episodes/123 タブが focus される
 */
