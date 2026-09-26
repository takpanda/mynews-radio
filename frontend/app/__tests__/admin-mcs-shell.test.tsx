import '@testing-library/jest-dom'

import { render, screen, waitFor, within } from '@testing-library/react'
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
    ;(global.fetch as jest.Mock)
      .mockResolvedValueOnce(jsonResponse(200, { ...activeMc, name: '田村（改）' }))
      .mockResolvedValueOnce(jsonResponse(200, [{ ...activeMc, name: '田村（改）' }]))

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
  })
})
