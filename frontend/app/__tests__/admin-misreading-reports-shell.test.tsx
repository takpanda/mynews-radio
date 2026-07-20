import '@testing-library/jest-dom'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import AdminMisreadingReportsShell from '../components/AdminMisreadingReportsShell'
import type { AdminMisreadingReport } from '../lib/admin-misreading-reports'

const sampleReports: AdminMisreadingReport[] = [
  {
    id: 1,
    target_text: '人工知能',
    correct_reading: 'じんこうちのう',
    article_id: 42,
    notes: '契約顧客の会話内で発生',
    created_at: '2026-07-20T00:00:00+00:00',
  },
  {
    id: 2,
    target_text: '機械学習',
    correct_reading: 'きかいがくしゅう',
    article_id: null,
    notes: '',
    created_at: '2026-07-19T12:00:00+00:00',
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

  it('ヘッダーにID/対象テキスト/正しい読み/記事ID/報告日時/メモの列が存在する', () => {
    render(<AdminMisreadingReportsShell initialData={sampleReports} />)
    expect(screen.getByText('ID')).toBeInTheDocument()
    expect(screen.getByText('対象テキスト')).toBeInTheDocument()
    expect(screen.getByText('正しい読み')).toBeInTheDocument()
    expect(screen.getByText('記事ID')).toBeInTheDocument()
    expect(screen.getByText('報告日時')).toBeInTheDocument()
    expect(screen.getByText('メモ')).toBeInTheDocument()
  })

  it('0件：空データの場合はメッセージを表示する', () => {
    render(<AdminMisreadingReportsShell initialData={[]} />)
    expect(screen.getByText('読み間違い報告はまだありません。')).toBeInTheDocument()
  })

  it('notesがある行に「表示」ボタンが表示される', () => {
    render(<AdminMisreadingReportsShell initialData={sampleReports} />)
    const showBtn = screen.getByRole('button', { name: '表示' })
    expect(showBtn).toBeInTheDocument()
  })

  it('notesがない行に「表示」ボタンは表示されない', () => {
    render(<AdminMisreadingReportsShell initialData={sampleReports} />)
    expect(screen.queryAllByRole('button', { name: '表示' })).toHaveLength(1)
  })

  it('「表示」クリックでnotesが展開される', async () => {
    const user = userEvent.setup()
    render(<AdminMisreadingReportsShell initialData={sampleReports} />)
    await user.click(screen.getByRole('button', { name: '表示' }))
    expect(screen.getByText('契約顧客の会話内で発生')).toBeInTheDocument()
  })

  it('展開後「閉じる」クリックでnotesが非表示になる', async () => {
    const user = userEvent.setup()
    render(<AdminMisreadingReportsShell initialData={sampleReports} />)

    await user.click(screen.getByRole('button', { name: '表示' }))
    expect(screen.getByText('契約顧客の会話内で発生')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: '閉じる' }))
    expect(screen.queryByText('契約顧客の会話内で発生')).not.toBeInTheDocument()
  })

  it('article_idがnullの場合は「—」を表示する', () => {
    render(<AdminMisreadingReportsShell initialData={sampleReports} />)
    const dashes = screen.getAllByText('—')
    expect(dashes.length).toBeGreaterThanOrEqual(1)
  })

  it('全件数がフッターに表示される', () => {
    render(<AdminMisreadingReportsShell initialData={sampleReports} />)
    expect(screen.getByText('全2件')).toBeInTheDocument()
  })
})
