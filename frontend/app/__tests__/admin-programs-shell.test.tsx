import '@testing-library/jest-dom'

import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import AdminProgramsShell from '../components/AdminProgramsShell'
import type { Program } from '../lib/admin-programs'

function jsonResponse(status: number, body: unknown) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: () => Promise.resolve(body),
    text: () => Promise.resolve(JSON.stringify(body)),
  }
}

const activeProgram: Program = {
  id: 'radio_news_neighbor',
  name: 'ニュースのとなり',
  kind: 'radio',
  definition: { id: 'radio_news_neighbor', name: 'ニュースのとなり', kind: 'radio', cast: [], segments: [], options: { style: null, mc_gender: null, narrative_arc: false, review_mode: 'on_failure' } },
  is_active: true,
  created_at: '',
  updated_at: '',
}

const inactiveProgram: Program = { ...activeProgram, id: 'old_program', name: '旧番組', is_active: false }

beforeEach(() => {
  global.fetch = jest.fn()
})

describe('AdminProgramsShell', () => {
  it('有効な番組のみ表示している状態で無効な番組は表示されない', () => {
    render(<AdminProgramsShell initialPrograms={[activeProgram]} initialIncludeInactive={false} />)
    expect(screen.getByText('ニュースのとなり')).toBeInTheDocument()
    expect(screen.queryByText('旧番組')).not.toBeInTheDocument()
  })

  it('「無効な番組も表示する」を有効にすると再取得して無効な番組も表示する', async () => {
    ;(global.fetch as jest.Mock).mockResolvedValueOnce(jsonResponse(200, [activeProgram, inactiveProgram]))
    const user = userEvent.setup()
    render(<AdminProgramsShell initialPrograms={[activeProgram]} initialIncludeInactive={false} />)

    await user.click(screen.getByRole('checkbox', { name: '無効な番組も表示する' }))

    expect(global.fetch).toHaveBeenCalledWith('/api/admin/programs?include_inactive=true', expect.anything())
    expect(await screen.findByText('旧番組')).toBeInTheDocument()
    expect(screen.getByText('無効')).toBeInTheDocument()
  })

  it('番組が0件のときは案内メッセージを表示する', () => {
    render(<AdminProgramsShell initialPrograms={[]} initialIncludeInactive={false} />)
    expect(screen.getByText('有効な番組がありません。')).toBeInTheDocument()
  })

  it('詳細リンクは各番組の編集ページを指す', () => {
    render(<AdminProgramsShell initialPrograms={[activeProgram]} initialIncludeInactive={false} />)
    expect(screen.getByRole('link', { name: '詳細' })).toHaveAttribute('href', '/admin/programs/radio_news_neighbor')
  })

  it('「番組を新規作成」はスマホ幅（375px相当）では非表示になるクラスを持つ', () => {
    // jsdomはメディアクエリを評価しないため、実際の375px非表示はPlaywright等の実ブラウザ確認が必要。
    // ここでは責務分割用のTailwindクラス（hidden / md:inline-flex）が外れていないことを回帰的に検知する。
    render(<AdminProgramsShell initialPrograms={[activeProgram]} initialIncludeInactive={false} />)
    const link = screen.getByRole('link', { name: '番組を新規作成' })
    expect(link).toHaveClass('hidden')
    expect(link).toHaveClass('md:inline-flex')
  })
})
