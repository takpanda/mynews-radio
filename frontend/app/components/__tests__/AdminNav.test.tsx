import '@testing-library/jest-dom'

import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import AdminNav from '../AdminNav'

const mockPush = jest.fn()
const mockRefresh = jest.fn()

jest.mock('next/navigation', () => ({
  useRouter: () => ({ push: mockPush, refresh: mockRefresh }),
}))

function jsonResponse(body: unknown) {
  return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(body), text: () => Promise.resolve(JSON.stringify(body)) })
}

beforeEach(() => {
  jest.clearAllMocks()
  global.fetch = jest.fn()
})

describe('AdminNav', () => {
  it('確認待ちが0件の場合はバッジを表示しない', async () => {
    ;(global.fetch as jest.Mock).mockReturnValue(jsonResponse([]))
    const { container } = render(<AdminNav />)
    await waitFor(() =>
      expect(global.fetch).toHaveBeenCalledWith('/api/admin/episodes?status=awaiting_review', expect.anything()),
    )
    expect(container.querySelectorAll('[aria-label$="件"]').length).toBe(0)
  })

  it('確認待ちがある場合は一覧と同じ取得結果に基づく件数バッジを表示する', async () => {
    ;(global.fetch as jest.Mock).mockReturnValue(jsonResponse([{ id: 1 }, { id: 2 }, { id: 3 }]))
    const { container } = render(<AdminNav />)
    await waitFor(() => expect(container.querySelectorAll('[aria-label="確認待ち3件"]').length).toBeGreaterThan(0))
  })

  it('取得に失敗してもナビゲーション自体は表示され続ける', async () => {
    ;(global.fetch as jest.Mock).mockReturnValue(Promise.resolve({ ok: false, status: 401, text: () => Promise.resolve('{}') }))
    render(<AdminNav />)
    await waitFor(() => expect(global.fetch).toHaveBeenCalled())
    expect(screen.getAllByRole('link', { name: '辞書管理' }).length).toBeGreaterThan(0)
    expect(screen.getAllByRole('link', { name: 'プロンプト管理' }).length).toBeGreaterThan(0)
  })

  it('スマホ幅のハンバーガーメニューから確認待ち一覧・既存管理画面・ログアウトへ移動できる', async () => {
    ;(global.fetch as jest.Mock).mockReturnValue(jsonResponse([]))
    const user = userEvent.setup()
    const { container } = render(<AdminNav />)

    const toggle = screen.getByRole('button', { name: 'メニューを開く' })
    expect(container.querySelector('#admin-nav-mobile-menu')).toBeNull()

    await user.click(toggle)
    expect(screen.getByRole('button', { name: 'メニューを閉じる' })).toBeInTheDocument()

    const menu = container.querySelector('#admin-nav-mobile-menu')
    expect(menu).not.toBeNull()
    expect(menu).toHaveTextContent('確認待ち一覧')
    expect(menu).toHaveTextContent('番組・MC管理')
    expect(menu).toHaveTextContent('プロンプト管理')
    expect(menu).toHaveTextContent('辞書管理')
    expect(menu).toHaveTextContent('読み間違い報告')
    expect(menu).toHaveTextContent('ボイス設定')
    expect(menu).toHaveTextContent('公開サイトへ')

    const logoutButtons = screen.getAllByRole('button', { name: 'ログアウト' })
    await user.click(logoutButtons[logoutButtons.length - 1])
    await waitFor(() => expect(global.fetch).toHaveBeenCalledWith('/api/admin/logout', { method: 'POST' }))
    expect(mockPush).toHaveBeenCalledWith('/admin/login')
    expect(mockRefresh).toHaveBeenCalled()
  })

  it('リンク追加で1行表示が窮屈にならないよう、横並び表示の開始幅はlg（1024px）にしている', async () => {
    ;(global.fetch as jest.Mock).mockReturnValue(jsonResponse([]))
    const { container } = render(<AdminNav />)

    const desktopLinks = container.querySelector('.hidden.items-center.gap-4')
    expect(desktopLinks).not.toBeNull()
    expect(desktopLinks).toHaveClass('hidden')
    expect(desktopLinks).toHaveClass('lg:flex')
    expect(desktopLinks).not.toHaveClass('md:flex')

    const hamburgerToggle = screen.getByRole('button', { name: 'メニューを開く' })
    expect(hamburgerToggle).toHaveClass('lg:hidden')
    expect(hamburgerToggle).not.toHaveClass('md:hidden')
  })
})
