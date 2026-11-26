/** @jest-environment node */

jest.mock('next/headers', () => ({
  cookies: jest.fn(() => ({ get: jest.fn(() => undefined) })),
}))
jest.mock('../lib/api', () => ({
  ...jest.requireActual('../lib/api'),
  fetchLatestEpisode: jest.fn(),
  fetchEpisodes: jest.fn(),
  fetchEpisodeScript: jest.fn(),
}))
jest.mock('../components/HomeShell', () => ({ __esModule: true, default: () => null }))

import Home from '../page'
import { fetchLatestEpisode, fetchEpisodes } from '../lib/api'

const normalPage = { items: [{ id: 1, title: '通常回' }], total: 1, has_next: false }

// 返り値の React 要素から HomeShell の props を取り出す
async function renderedShellProps() {
  const page = (await Home()) as { props: { children: { props: Record<string, unknown> } } }
  return page.props.children.props
}

describe('トップページ SSR のダイジェスト取得', () => {
  beforeEach(() => {
    jest.clearAllMocks()
    ;(fetchLatestEpisode as jest.Mock).mockResolvedValue(null)
  })

  it('ダイジェスト取得だけが失敗しても通常一覧を渡し、ダイジェストは空にする', async () => {
    ;(fetchEpisodes as jest.Mock).mockImplementation((_l: number, _o: number, _s: unknown, category?: string) =>
      category === 'digest' ? Promise.reject(new Error('boom')) : Promise.resolve(normalPage),
    )
    const props = await renderedShellProps()
    expect(props.initialEpisodes).toEqual(normalPage.items)
    expect(props.initialDigestEpisodes).toEqual([])
  })

  it('ダイジェスト取得に成功したときは先頭ページを渡す', async () => {
    const digestPage = { items: [{ id: 9, title: 'ダイジェスト', type: 'digest' }], total: 1, has_next: false }
    ;(fetchEpisodes as jest.Mock).mockImplementation((_l: number, _o: number, _s: unknown, category?: string) =>
      Promise.resolve(category === 'digest' ? digestPage : normalPage),
    )
    const props = await renderedShellProps()
    expect(props.initialDigestEpisodes).toEqual(digestPage.items)
  })

  it('ダイジェスト取得が上限時間を超えても通常一覧を表示する', async () => {
    jest.useFakeTimers()
    try {
      ;(fetchEpisodes as jest.Mock).mockImplementation((_l: number, _o: number, _s: unknown, category?: string) =>
        category === 'digest' ? new Promise(() => {}) : Promise.resolve(normalPage),
      )
      const pending = renderedShellProps()
      await jest.advanceTimersByTimeAsync(3500)
      const props = await pending
      expect(props.initialEpisodes).toEqual(normalPage.items)
      expect(props.initialDigestEpisodes).toEqual([])
    } finally {
      jest.useRealTimers()
    }
  })
})
