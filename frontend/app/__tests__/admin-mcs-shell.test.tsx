import '@testing-library/jest-dom'

import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import AdminMcsShell from '../components/AdminMcsShell'
import type { Mc } from '../lib/admin-programs'

function jsonResponse(status: number, body: unknown) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: () => Promise.resolve(body),
    text: () => Promise.resolve(JSON.stringify(body)),
  }
}

const activeMc: Mc = {
  id: 'radio_male',
  name: '田村',
  role: 'メインMC',
  voice_fishs2pro: null,
  voice_aivispeech: 123,
  voice_voicevox: null,
  is_active: true,
  created_at: '',
  updated_at: '',
}

const VOICE_OPTIONS = {
  aivispeech: { status: 'ok', options: [], error: null },
  voicevox: { status: 'ok', options: [], error: null },
  fishs2pro: { status: 'ok', options: [], error: null },
}

beforeEach(() => {
  global.fetch = jest.fn()
})

describe('AdminMcsShell', () => {
  it('MC一覧をID・名前・状態付きで表示する', () => {
    render(<AdminMcsShell initialMcs={[activeMc]} initialIncludeInactive={false} />)
    expect(screen.getByText('radio_male')).toBeInTheDocument()
    expect(screen.getByText('田村')).toBeInTheDocument()
    expect(screen.getByText('有効')).toBeInTheDocument()
  })

  it('MCが0件のときは案内メッセージを表示する', () => {
    render(<AdminMcsShell initialMcs={[]} initialIncludeInactive={false} />)
    expect(screen.getByText('有効なMCがありません。')).toBeInTheDocument()
  })

  it('編集からモーダルを開き、保存すると一覧が再取得される', async () => {
    // モーダル表示時のボイス候補取得（GET .../voices/options）と、保存（PUT）・保存後の一覧再取得（GET .../mcs）をURL・メソッドで振り分ける
    const updatedMc = { ...activeMc, name: '田村（改）' }
    ;(global.fetch as jest.Mock).mockImplementation((url: string, options?: RequestInit) => {
      if (url.includes('/settings/voices/options')) return Promise.resolve(jsonResponse(200, VOICE_OPTIONS))
      if (options?.method === 'PUT') return Promise.resolve(jsonResponse(200, updatedMc))
      return Promise.resolve(jsonResponse(200, [updatedMc]))
    })

    const user = userEvent.setup()
    render(<AdminMcsShell initialMcs={[activeMc]} initialIncludeInactive={false} />)

    await user.click(screen.getByRole('button', { name: '編集' }))
    const dialog = await screen.findByRole('dialog')
    const nameInput = within(dialog).getByDisplayValue('田村')
    await user.clear(nameInput)
    await user.type(nameInput, '田村（改）')
    await user.click(within(dialog).getByRole('button', { name: '保存する' }))

    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    expect(await screen.findByText('田村（改）')).toBeInTheDocument()

    const calls = (global.fetch as jest.Mock).mock.calls as [string, RequestInit?][]
    expect(calls.some(([url, o]) => o?.method === 'PUT' && url.includes('/admin/mcs/radio_male'))).toBe(true)
    expect(calls.some(([url, o]) => !o?.method && /\/admin\/mcs(\?|$)/.test(url))).toBe(true)
  })

  it('「MCを追加」ボタンはスマホ幅では非表示、編集ボタンは非表示クラスを持たない', () => {
    // jsdomはメディアクエリを評価しないため、実際の375px表示は実ブラウザ確認が必要。クラスの回帰のみ検知する。
    render(<AdminMcsShell initialMcs={[activeMc]} initialIncludeInactive={false} />)
    const addButton = screen.getByRole('button', { name: 'MCを追加' })
    expect(addButton).toHaveClass('hidden')
    expect(addButton).toHaveClass('md:inline-flex')

    const editButton = screen.getByRole('button', { name: '編集' })
    expect(editButton.closest('td')).not.toHaveClass('hidden')
    expect(editButton.closest('td')).not.toHaveClass('md:table-cell')
  })

  it('行タップで編集モーダルが開く', async () => {
    const user = userEvent.setup()
    render(<AdminMcsShell initialMcs={[activeMc]} initialIncludeInactive={false} />)
    await user.click(screen.getByText(activeMc.id))
    expect(await screen.findByRole('dialog')).toBeInTheDocument()
  })

  it('編集ボタンのクリックは行へ伝播しない（stopPropagationで二重発火を防ぐ）', async () => {
    // Reactのルート(RTLのcontainer)で止まらなければ、bodyのリスナーに届く＝行のonClickも発火する
    const bubbled = jest.fn()
    document.body.addEventListener('click', bubbled)
    try {
      const user = userEvent.setup()
      render(<AdminMcsShell initialMcs={[activeMc]} initialIncludeInactive={false} />)
      await user.click(screen.getByRole('button', { name: '編集' }))
      expect(await screen.findByRole('dialog')).toBeInTheDocument()
      expect(bubbled).not.toHaveBeenCalled()

      // 対照: 行（編集ボタン以外）のクリックは通常どおり伝播する
      await user.click(screen.getByRole('button', { name: '閉じる' }))
      await user.click(screen.getByText(activeMc.id))
      expect(bubbled).toHaveBeenCalled()
    } finally {
      document.body.removeEventListener('click', bubbled)
    }
  })

  it('写真未登録はプレースホルダー（頭文字）、登録済みは画像を表示し、読込失敗でプレースホルダーに戻る', () => {
    const withPhoto: Mc = { ...activeMc, id: 'p', name: '山口', photo_url: '/api/mcs/p/photo?v=abc' }
    render(<AdminMcsShell initialMcs={[activeMc, withPhoto]} initialIncludeInactive={false} />)
    expect(screen.getAllByTestId('mc-photo-placeholder')).toHaveLength(1)
    expect(screen.getByTestId('mc-photo-placeholder')).toHaveTextContent('田')
    const img = screen.getByAltText('山口の写真')
    expect(img).toHaveAttribute('src', '/api/mcs/p/photo?v=abc')
    fireEvent.error(img)
    expect(screen.getAllByTestId('mc-photo-placeholder')).toHaveLength(2)
  })

  it('新規作成: JSON保存→写真アップロードの順で呼ばれ、成功するとモーダルが閉じる', async () => {
    const order: string[] = []
    ;(global.fetch as jest.Mock).mockImplementation((url: string, options?: RequestInit) => {
      if (url.includes('/settings/voices/options')) return Promise.resolve(jsonResponse(200, VOICE_OPTIONS))
      if (options?.method === 'POST') order.push(url)
      if (options?.method === 'POST') return Promise.resolve(jsonResponse(200, activeMc))
      return Promise.resolve(jsonResponse(200, [activeMc]))
    })
    global.URL.createObjectURL = jest.fn(() => 'blob:x')
    global.URL.revokeObjectURL = jest.fn()
    const user = userEvent.setup()
    render(<AdminMcsShell initialMcs={[]} initialIncludeInactive={false} />)
    await user.click(screen.getByRole('button', { name: 'MCを追加' }))
    const dialog = await screen.findByRole('dialog')
    await user.type(within(dialog).getByPlaceholderText('例: radio_male'), 'radio_male')
    const file = new File(['x'], 'a.png', { type: 'image/png' })
    await user.upload(within(dialog).getByLabelText('MC写真を選択'), file)
    expect(within(dialog).getByAltText('MC写真のプレビュー')).toBeInTheDocument()
    await user.click(within(dialog).getByRole('button', { name: '追加する' }))
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    expect(order).toEqual(['/api/admin/mcs', '/api/admin/mcs/radio_male/photo'])
  })

  it('写真のみ失敗した場合はモーダルを閉じず、MC本体は保存済みと表示する', async () => {
    ;(global.fetch as jest.Mock).mockImplementation((url: string, options?: RequestInit) => {
      if (url.includes('/settings/voices/options')) return Promise.resolve(jsonResponse(200, VOICE_OPTIONS))
      if (url.endsWith('/photo')) return Promise.resolve(jsonResponse(422, { detail: '画像を読み込めません' }))
      if (options?.method === 'PUT') return Promise.resolve(jsonResponse(200, activeMc))
      return Promise.resolve(jsonResponse(200, [activeMc]))
    })
    global.URL.createObjectURL = jest.fn(() => 'blob:x')
    global.URL.revokeObjectURL = jest.fn()
    const user = userEvent.setup()
    render(<AdminMcsShell initialMcs={[activeMc]} initialIncludeInactive={false} />)
    await user.click(screen.getByRole('button', { name: '編集' }))
    const dialog = await screen.findByRole('dialog')
    await user.upload(within(dialog).getByLabelText('MC写真を選択'), new File(['x'], 'a.png', { type: 'image/png' }))
    await user.click(within(dialog).getByRole('button', { name: '保存する' }))
    expect(await within(dialog).findByText(/MC情報は保存されましたが、写真の更新に失敗しました/)).toBeInTheDocument()
    expect(screen.getByRole('dialog')).toBeInTheDocument()
  })

  it('5MB超の画像は選択時点で弾かれ、アップロードされない', async () => {
    ;(global.fetch as jest.Mock).mockImplementation((url: string) => {
      if (url.includes('/settings/voices/options')) return Promise.resolve(jsonResponse(200, VOICE_OPTIONS))
      return Promise.resolve(jsonResponse(200, []))
    })
    const user = userEvent.setup()
    render(<AdminMcsShell initialMcs={[activeMc]} initialIncludeInactive={false} />)
    await user.click(screen.getByRole('button', { name: '編集' }))
    const dialog = await screen.findByRole('dialog')
    const big = new File(['x'], 'big.png', { type: 'image/png' })
    Object.defineProperty(big, 'size', { value: 5 * 1024 * 1024 + 1 })
    await user.upload(within(dialog).getByLabelText('MC写真を選択'), big)
    expect(within(dialog).getByText('画像のサイズは5MB以下にしてください')).toBeInTheDocument()
    expect(within(dialog).queryByAltText('MC写真のプレビュー')).not.toBeInTheDocument()
  })

  it('登録済み写真を削除して保存すると DELETE が呼ばれる', async () => {
    const mcWithPhoto: Mc = { ...activeMc, photo_url: '/api/mcs/radio_male/photo?v=abc' }
    const calls: [string, string | undefined][] = []
    ;(global.fetch as jest.Mock).mockImplementation((url: string, options?: RequestInit) => {
      calls.push([url, options?.method])
      if (url.includes('/settings/voices/options')) return Promise.resolve(jsonResponse(200, VOICE_OPTIONS))
      if (options?.method === 'DELETE') return Promise.resolve(jsonResponse(200, activeMc))
      if (options?.method === 'PUT') return Promise.resolve(jsonResponse(200, activeMc))
      return Promise.resolve(jsonResponse(200, [activeMc]))
    })
    const user = userEvent.setup()
    render(<AdminMcsShell initialMcs={[mcWithPhoto]} initialIncludeInactive={false} />)
    await user.click(screen.getByRole('button', { name: '編集' }))
    const dialog = await screen.findByRole('dialog')
    await user.click(within(dialog).getByRole('button', { name: '写真を削除' }))
    await user.click(within(dialog).getByRole('button', { name: '保存する' }))
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    expect(calls).toContainEqual(['/api/admin/mcs/radio_male/photo', 'DELETE'])
  })
})
