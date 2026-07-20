import '@testing-library/jest-dom'
import { render, screen, waitFor, act } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import AdminMisreadingReportsShell from '../components/AdminMisreadingReportsShell'
import type { AdminMisreadingReport } from '../lib/admin-misreading-reports'

const mockApprove = jest.fn()
jest.mock('../lib/admin-misreading-reports', () => {
  const actual = jest.requireActual('../lib/admin-misreading-reports')
  return {
    ...actual,
    approveMisreadingReport: (...args: unknown[]) => mockApprove(...args),
  }
})

const sampleReports: AdminMisreadingReport[] = [
  {
    id: 1,
    target_text: '人工知能',
    correct_reading: 'じんこうちのう',
    article_id: 42,
    notes: '契約顧客の会話内で発生',
    approved: false,
    approved_at: null,
    approved_dictionary_entry_id: null,
    created_at: '2026-07-20T00:00:00+00:00',
  },
  {
    id: 2,
    target_text: '機械学習',
    correct_reading: 'きかいがくしゅう',
    article_id: null,
    notes: '',
    approved: true,
    approved_at: '2026-07-20T01:00:00+00:00',
    approved_dictionary_entry_id: 5,
    created_at: '2026-07-19T12:00:00+00:00',
  },
  {
    id: 3,
    target_text: '深層学習',
    correct_reading: 'しんそうがくしゅう',
    article_id: null,
    notes: 'ニュース番組内で発生',
    approved: false,
    approved_at: null,
    approved_dictionary_entry_id: null,
    created_at: '2026-07-18T12:00:00+00:00',
  },
]

describe('AdminMisreadingReportsShell', () => {
  it('正常系：報告一覧が表形式で表示される', () => {
    render(<AdminMisreadingReportsShell initialData={sampleReports} />)
    expect(screen.getByText('読み間違い報告')).toBeInTheDocument()
    expect(screen.getByText('人工知能')).toBeInTheDocument()
    expect(screen.getByText('じんこうちのう')).toBeInTheDocument()
    expect(screen.getByText('きかいがくしゅう')).toBeInTheDocument()
    expect(screen.getByText('42')).toBeInTheDocument()
  })

  it('ヘッダーにID/対象テキスト/正しい読み/記事ID/報告日時/状態/操作の列が存在する', () => {
    render(<AdminMisreadingReportsShell initialData={sampleReports} />)
    expect(screen.getByText('ID')).toBeInTheDocument()
    expect(screen.getByText('対象テキスト')).toBeInTheDocument()
    expect(screen.getByText('正しい読み')).toBeInTheDocument()
    expect(screen.getByText('記事ID')).toBeInTheDocument()
    expect(screen.getByText('報告日時')).toBeInTheDocument()
    expect(screen.getByText('状態')).toBeInTheDocument()
    expect(screen.getByText('操作')).toBeInTheDocument()
  })

  it('0件：空データの場合はメッセージを表示する', () => {
    render(<AdminMisreadingReportsShell initialData={[]} />)
    expect(screen.getByText('読み間違い報告はまだありません。')).toBeInTheDocument()
  })

  it('notesがある行に「メモ」ボタンが表示される', () => {
    render(<AdminMisreadingReportsShell initialData={sampleReports} />)
    const memoBtns = screen.getAllByRole('button', { name: 'メモ' })
    expect(memoBtns).toHaveLength(2)
  })

  it('notesのある2行のみ「メモ」ボタンが表示される', () => {
    render(<AdminMisreadingReportsShell initialData={sampleReports} />)
    expect(screen.queryAllByRole('button', { name: 'メモ' })).toHaveLength(2)
  })

  it('「メモ」クリックでnotesが展開される', async () => {
    const user = userEvent.setup()
    render(<AdminMisreadingReportsShell initialData={sampleReports} />)
    const memoBtns = screen.getAllByRole('button', { name: 'メモ' })
    await user.click(memoBtns[0])
    expect(screen.getByText('契約顧客の会話内で発生')).toBeInTheDocument()
  })

  it('展開後「メモを閉じる」クリックでnotesが非表示になる', async () => {
    const user = userEvent.setup()
    render(<AdminMisreadingReportsShell initialData={sampleReports} />)

    const memoBtns = screen.getAllByRole('button', { name: 'メモ' })
    await user.click(memoBtns[0])
    expect(screen.getByText('契約顧客の会話内で発生')).toBeInTheDocument()

    const closeBtns = screen.getAllByRole('button', { name: 'メモを閉じる' })
    await user.click(closeBtns[0])
    expect(screen.queryByText('契約顧客の会話内で発生')).not.toBeInTheDocument()
  })

  it('article_idがnullの場合は「—」を表示する', () => {
    render(<AdminMisreadingReportsShell initialData={sampleReports} />)
    const dashes = screen.getAllByText('—')
    expect(dashes.length).toBeGreaterThanOrEqual(1)
  })

  it('全件数がフッターに表示される', () => {
    render(<AdminMisreadingReportsShell initialData={sampleReports} />)
    expect(screen.getByText('全3件')).toBeInTheDocument()
  })

  it('未承認の報告に「承認」ボタンが表示される', () => {
    render(<AdminMisreadingReportsShell initialData={sampleReports} />)
    const approveBtns = screen.getAllByRole('button', { name: '承認' })
    expect(approveBtns).toHaveLength(2)
  })

  it('承認済みの報告に「承認」ボタンが表示されず「承認済み」ラベルが表示される', () => {
    render(<AdminMisreadingReportsShell initialData={sampleReports} />)
    expect(screen.getByText('承認済み')).toBeInTheDocument()
    expect(screen.getAllByText('未承認')).toHaveLength(2)
  })

  it('「承認済み」が1件、「未承認」が2件表示される', () => {
    render(<AdminMisreadingReportsShell initialData={sampleReports} />)
    expect(screen.getAllByText('承認済み')).toHaveLength(1)
    expect(screen.getAllByText('未承認')).toHaveLength(2)
  })

  it('承認成功(approved) → 承認済みが2件、承認ボタンが1つになる', async () => {
    mockApprove.mockResolvedValueOnce({
      status: 'approved',
      report_id: 1,
      dictionary_entry_id: 10,
    })
    const user = userEvent.setup()
    render(<AdminMisreadingReportsShell initialData={sampleReports} />)
    const approveBtns = screen.getAllByRole('button', { name: '承認' })

    await user.click(approveBtns[0])
    await waitFor(() => {
      expect(screen.getAllByText('承認済み')).toHaveLength(2)
      expect(screen.getAllByRole('button', { name: '承認' })).toHaveLength(1)
    })
  })

  it('重複スキップ(skipped) → 承認済みが2件、承認ボタンが1つになる', async () => {
    mockApprove.mockResolvedValueOnce({
      status: 'skipped',
      report_id: 1,
      reason: 'duplicate_original',
      existing_entry_id: 10,
    })
    const user = userEvent.setup()
    render(<AdminMisreadingReportsShell initialData={sampleReports} />)
    const approveBtns = screen.getAllByRole('button', { name: '承認' })

    await user.click(approveBtns[0])
    await waitFor(() => {
      expect(screen.getAllByText('承認済み')).toHaveLength(2)
      expect(screen.getAllByRole('button', { name: '承認' })).toHaveLength(1)
    })
  })

  it('既承認(already_approved) → 承認済みが2件になる', async () => {
    mockApprove.mockResolvedValueOnce({
      status: 'already_approved',
      report_id: 1,
      dictionary_entry_id: 10,
    })
    const user = userEvent.setup()
    render(<AdminMisreadingReportsShell initialData={sampleReports} />)
    const approveBtns = screen.getAllByRole('button', { name: '承認' })

    await user.click(approveBtns[0])
    await waitFor(() => {
      expect(screen.getAllByText('承認済み')).toHaveLength(2)
    })
  })

  it('API失敗 → 未承認は2件のまま', async () => {
    mockApprove.mockRejectedValueOnce(new Error('Network error'))
    const user = userEvent.setup()
    render(<AdminMisreadingReportsShell initialData={sampleReports} />)
    const approveBtns = screen.getAllByRole('button', { name: '承認' })

    await user.click(approveBtns[0])
    await waitFor(() => {
      expect(screen.getAllByText('未承認')).toHaveLength(2)
    })
  })

  it('承認中はボタンがdisabledになり処理中が表示される', async () => {
    let deferredResolve: (v: unknown) => void = () => {}
    mockApprove.mockImplementationOnce(
      () => new Promise((resolve) => { deferredResolve = resolve }),
    )
    const user = userEvent.setup()
    render(<AdminMisreadingReportsShell initialData={sampleReports} />)
    const approveBtns = screen.getAllByRole('button', { name: '承認' })

    await user.click(approveBtns[0])
    expect(screen.getByText('処理中...')).toBeInTheDocument()

    await act(async () => {
      deferredResolve({ status: 'approved', report_id: 1, dictionary_entry_id: 10 })
    })
    expect(screen.queryByText('処理中...')).not.toBeInTheDocument()
  })
})
