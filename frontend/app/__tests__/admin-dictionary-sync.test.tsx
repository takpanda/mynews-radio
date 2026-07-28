import '@testing-library/jest-dom'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import AdminDictionaryShell from '../components/AdminDictionaryShell'
import type { PaginatedDictionaryResponse } from '../lib/admin-dictionary'

const mockSync = jest.fn()
jest.mock('../lib/admin-dictionary', () => {
  const actual = jest.requireActual('../lib/admin-dictionary')
  return {
    ...actual,
    syncDictionaryEntries: (...args: unknown[]) => mockSync(...args),
  }
})

const initialData: PaginatedDictionaryResponse = {
  items: [
    { id: 1, word: '新規語', reading: 'しんきご', category: '技術用語', status: 'active', notes: '', source_misreading_report_id: null, updated_at: '2026-07-27T10:00:00Z' },
    { id: 2, word: '既存語', reading: 'きご', category: '固有名詞', status: 'active', notes: '', source_misreading_report_id: null, updated_at: '2026-07-27T10:00:00Z' },
  ],
  total: 2,
  has_next: false,
  stats: { total: 2, active: 2, inactive: 0 },
}

describe('AdminDictionaryShell AIVIS Sync', () => {
  beforeEach(() => {
    mockSync.mockReset()
  })

  it('同期ボタンは選択がないとき表示されない', () => {
    render(<AdminDictionaryShell initialData={initialData} />)
    expect(screen.queryByRole('button', { name: /AIVISに同期/ })).not.toBeInTheDocument()
  })

  it('選択後に同期ボタンが表示される', async () => {
    const user = userEvent.setup()
    render(<AdminDictionaryShell initialData={initialData} />)
    const cb = screen.getByLabelText('新規語を選択')
    await user.click(cb)
    expect(screen.getByRole('button', { name: /AIVISに同期（1）/ })).toBeInTheDocument()
  })

  it('混在選択(新規+既存)でキャンセル時はadd_wordが呼ばれない', async () => {
    const user = userEvent.setup()
    mockSync.mockResolvedValueOnce({
      synced_at: '2026-07-27T12:00:00Z',
      added: 0,
      updated: 0,
      deleted: 0,
      skipped: 2,
      errors: 0,
      details: [
        { dictionary_entry_id: 1, surface: '新規語', status: 'pending', reason: 'not_found', reading: 'しんきご' },
        { dictionary_entry_id: 2, surface: '既存語', status: 'confirmation_required', reason: 'remote_exists' },
      ],
    })

    render(<AdminDictionaryShell initialData={initialData} />)

    const cb1 = screen.getByLabelText('新規語を選択')
    const cb2 = screen.getByLabelText('既存語を選択')
    await user.click(cb1)
    await user.click(cb2)

    const syncBtn = screen.getByRole('button', { name: /AIVISに同期（2）/ })
    await user.click(syncBtn)

    await waitFor(() => {
      expect(screen.getByText('上書き確認')).toBeInTheDocument()
      expect(screen.getAllByText('既存語')).toHaveLength(2)
    })

    expect(mockSync).toHaveBeenCalledTimes(1)
    expect(mockSync).toHaveBeenCalledWith([1, 2], false, true)

    const cancelBtn = screen.getByText('キャンセル')
    await user.click(cancelBtn)

    expect(screen.queryByText('上書き確認')).not.toBeInTheDocument()
    expect(mockSync).toHaveBeenCalledTimes(1)
  })

  it('混在選択で確認後は全IDがoverwrite_confirmed=trueで送信される', async () => {
    const user = userEvent.setup()
    mockSync
      .mockResolvedValueOnce({
        synced_at: '2026-07-27T12:00:00Z',
        added: 0,
        updated: 0,
        deleted: 0,
        skipped: 2,
        errors: 0,
        details: [
          { dictionary_entry_id: 1, surface: '新規語', status: 'pending', reason: 'not_found', reading: 'しんきご' },
          { dictionary_entry_id: 2, surface: '既存語', status: 'confirmation_required', reason: 'remote_exists' },
        ],
      })
      .mockResolvedValueOnce({
        synced_at: '2026-07-27T12:00:01Z',
        added: 1,
        updated: 1,
        deleted: 0,
        skipped: 0,
        errors: 0,
        details: [
          { dictionary_entry_id: 1, surface: '新規語', status: 'added', reason: 'not_found', reading: 'しんきご' },
          { dictionary_entry_id: 2, surface: '既存語', status: 'updated', reason: 'overwritten', reading: 'きご' },
        ],
      })

    render(<AdminDictionaryShell initialData={initialData} />)

    const cb1 = screen.getByLabelText('新規語を選択')
    const cb2 = screen.getByLabelText('既存語を選択')
    await user.click(cb1)
    await user.click(cb2)

    const syncBtn = screen.getByRole('button', { name: /AIVISに同期（2）/ })
    await user.click(syncBtn)

    await waitFor(() => {
      expect(screen.getByText('上書き確認')).toBeInTheDocument()
    })

    const confirmBtn = screen.getByText('上書きして同期')
    await user.click(confirmBtn)

    await waitFor(() => {
      expect(screen.getByText('同期結果')).toBeInTheDocument()
    })

    expect(mockSync).toHaveBeenCalledTimes(2)
    expect(mockSync).toHaveBeenNthCalledWith(1, [1, 2], false, true)
    expect(mockSync).toHaveBeenNthCalledWith(2, [1, 2], true, false)
  })

  it('混在なし(全エントリ新規)は確認ダイアログなしで結果表示', async () => {
    const user = userEvent.setup()
    mockSync
      .mockResolvedValueOnce({
        synced_at: '2026-07-27T12:00:00Z',
        added: 0,
        updated: 0,
        deleted: 0,
        skipped: 1,
        errors: 0,
        details: [
          { dictionary_entry_id: 1, surface: '新規語', status: 'pending', reason: 'not_found', reading: 'しんきご' },
        ],
      })
      .mockResolvedValueOnce({
        synced_at: '2026-07-27T12:00:01Z',
        added: 1,
        updated: 0,
        deleted: 0,
        skipped: 0,
        errors: 0,
        details: [
          { dictionary_entry_id: 1, surface: '新規語', status: 'added', reason: 'not_found', reading: 'しんきご' },
        ],
      })

    render(<AdminDictionaryShell initialData={initialData} />)

    const cb1 = screen.getByLabelText('新規語を選択')
    await user.click(cb1)

    const syncBtn = screen.getByRole('button', { name: /AIVISに同期（1）/ })
    await user.click(syncBtn)

    await waitFor(() => {
      expect(screen.getByText('同期結果')).toBeInTheDocument()
    })

    expect(screen.queryByText('上書き確認')).not.toBeInTheDocument()
    expect(mockSync).toHaveBeenCalledTimes(2)
    expect(mockSync).toHaveBeenNthCalledWith(2, [1], true, false)
  })
})
