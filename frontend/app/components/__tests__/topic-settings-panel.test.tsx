import '@testing-library/jest-dom'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import TopicSettingsPanel from '../TopicSettingsPanel'

const limits = { max_topics: 20, name_max_length: 40, description_max_length: 200 }
const topic = (id: number, name: string, weight = 'medium') => ({ id, name, description: '', weight, is_active: true })

function res(status: number, body?: unknown) {
  return { ok: status >= 200 && status < 300, status, json: () => Promise.resolve(body), text: () => Promise.resolve(body === undefined ? '' : JSON.stringify(body)) }
}

beforeEach(() => { global.fetch = jest.fn() })
const fetchMock = () => global.fetch as jest.Mock

describe('TopicSettingsPanel', () => {
  it('一覧を表示し、radiogroup と aria-label が付く', async () => {
    fetchMock().mockResolvedValueOnce(res(200, { topics: [topic(1, 'ローカルLLM', 'high')], limits }))
    render(<TopicSettingsPanel />)
    expect(await screen.findByRole('radiogroup', { name: '比重: ローカルLLM' })).toBeInTheDocument()
    expect(screen.getByLabelText('トピック名: ローカルLLM')).toHaveValue('ローカルLLM')
    expect(screen.getByLabelText('ローカルLLMの比重 高')).toBeChecked()
    expect(screen.getByText(/関連しそうな言葉を書くと判定が安定します/)).toBeInTheDocument()
  })

  it('追加できる', async () => {
    fetchMock()
      .mockResolvedValueOnce(res(200, { topics: [], limits }))
      .mockResolvedValueOnce(res(201, topic(2, 'AI')))
    render(<TopicSettingsPanel />)
    await userEvent.type(await screen.findByLabelText('新しいトピック名'), 'AI')
    await userEvent.click(screen.getByRole('button', { name: '追加' }))
    expect(await screen.findByLabelText('トピック名: AI')).toBeInTheDocument()
    expect(JSON.parse(fetchMock().mock.calls[1][1].body)).toEqual({ name: 'AI', description: '', weight: 'medium' })
  })

  it('20件で追加フォームが無効になる', async () => {
    const topics = Array.from({ length: 20 }, (_, i) => topic(i + 1, `t${i}`))
    fetchMock().mockResolvedValueOnce(res(200, { topics, limits }))
    render(<TopicSettingsPanel />)
    expect(await screen.findByLabelText('新しいトピック名')).toBeDisabled()
    expect(screen.getByRole('button', { name: '追加' })).toBeDisabled()
  })

  it('409 でエラー表示し、追加されない', async () => {
    fetchMock()
      .mockResolvedValueOnce(res(200, { topics: [topic(1, 'AI')], limits }))
      .mockResolvedValueOnce(res(409, { detail: 'dup' }))
    render(<TopicSettingsPanel />)
    await userEvent.type(await screen.findByLabelText('新しいトピック名'), 'ai')
    await userEvent.click(screen.getByRole('button', { name: '追加' }))
    expect(await screen.findByText('同じ名前のトピックが既にあります')).toBeInTheDocument()
    expect(screen.getAllByRole('listitem')).toHaveLength(1)
  })

  it('比重変更が失敗したら元に戻りエラーが出る(503)', async () => {
    fetchMock()
      .mockResolvedValueOnce(res(200, { topics: [topic(1, 'AI', 'medium')], limits }))
      .mockResolvedValueOnce(res(503, { detail: '関心トピックを保存できませんでした' }))
    render(<TopicSettingsPanel />)
    await userEvent.click(await screen.findByLabelText('AIの比重 高'))
    expect(await screen.findByText('関心トピックを保存できませんでした')).toBeInTheDocument()
    expect(screen.getByLabelText('AIの比重 中')).toBeChecked()
  })

  it('名前の更新が422なら入力が元に戻る', async () => {
    fetchMock()
      .mockResolvedValueOnce(res(200, { topics: [topic(1, 'AI')], limits }))
      .mockResolvedValueOnce(res(422, { detail: [{ msg: 'bad' }] }))
    render(<TopicSettingsPanel />)
    const input = await screen.findByLabelText('トピック名: AI')
    await userEvent.type(input, 'X')
    await userEvent.tab()
    expect(await screen.findByText(/入力内容が正しくありません/)).toBeInTheDocument()
    await waitFor(() => expect(input).toHaveValue('AI'))
  })

  it('空の名前に更新しようとするとAPIを呼ばず元に戻る', async () => {
    fetchMock().mockResolvedValueOnce(res(200, { topics: [topic(1, 'AI')], limits }))
    render(<TopicSettingsPanel />)
    const input = await screen.findByLabelText('トピック名: AI')
    await userEvent.clear(input)
    await userEvent.tab()
    expect(await screen.findByText('トピック名を入力してください')).toBeInTheDocument()
    expect(input).toHaveValue('AI')
    expect(fetchMock()).toHaveBeenCalledTimes(1)
  })

  it('削除できる / 401 のとき削除は元に戻りログイン案内が出る', async () => {
    fetchMock()
      .mockResolvedValueOnce(res(200, { topics: [topic(1, 'AI')], limits }))
      .mockResolvedValueOnce(res(401, { detail: 'x' }))
    render(<TopicSettingsPanel />)
    await userEvent.click(await screen.findByRole('button', { name: 'AIを削除' }))
    expect(await screen.findByText(/ログインが必要です/)).toBeInTheDocument()
    expect(screen.getByLabelText('トピック名: AI')).toBeInTheDocument()
  })

  it('削除成功(204)で一覧から消える', async () => {
    fetchMock()
      .mockResolvedValueOnce(res(200, { topics: [topic(1, 'AI')], limits }))
      .mockResolvedValueOnce(res(204))
    render(<TopicSettingsPanel />)
    await userEvent.click(await screen.findByRole('button', { name: 'AIを削除' }))
    await waitFor(() => expect(screen.queryByLabelText('トピック名: AI')).not.toBeInTheDocument())
  })

  it('テキスト保存中に比重をクリックしても操作が失われず、順番に保存される', async () => {
    let resolveFirst: (v: unknown) => void = () => {}
    fetchMock()
      .mockResolvedValueOnce(res(200, { topics: [topic(1, 'AI')], limits }))
      .mockImplementationOnce(() => new Promise((r) => { resolveFirst = r }))
      .mockResolvedValueOnce(res(200, { ...topic(1, 'AIX', 'high') }))
    render(<TopicSettingsPanel />)
    const input = await screen.findByLabelText('トピック名: AI')
    await userEvent.type(input, 'X')
    await userEvent.click(screen.getByLabelText('AIの比重 高'))
    expect(input).not.toBeDisabled()
    expect(fetchMock()).toHaveBeenCalledTimes(2)
    resolveFirst(res(200, topic(1, 'AIX')))
    await waitFor(() => expect(fetchMock()).toHaveBeenCalledTimes(3))
    expect(JSON.parse(fetchMock().mock.calls[2][1].body)).toEqual({ name: 'AIX', description: '', weight: 'high', is_active: true })
    await waitFor(() => expect(screen.getByLabelText('AIXの比重 高')).toBeChecked())
  })

  it('無効なトピックの更新で is_active=false を維持する', async () => {
    fetchMock()
      .mockResolvedValueOnce(res(200, { topics: [{ ...topic(1, 'AI'), is_active: false }], limits }))
      .mockResolvedValueOnce(res(200, { ...topic(1, 'AI', 'high'), is_active: false }))
    render(<TopicSettingsPanel />)
    await userEvent.click(await screen.findByLabelText('AIの比重 高'))
    await waitFor(() => expect(fetchMock()).toHaveBeenCalledTimes(2))
    expect(JSON.parse(fetchMock().mock.calls[1][1].body).is_active).toBe(false)
  })

  it('一覧取得に失敗したら追加できず、再読み込みで復帰する', async () => {
    fetchMock()
      .mockResolvedValueOnce(res(500, {}))
      .mockResolvedValueOnce(res(200, { topics: [topic(1, 'AI')], limits }))
    render(<TopicSettingsPanel />)
    expect(await screen.findByText(/読み込みに失敗しました/)).toBeInTheDocument()
    expect(screen.getByLabelText('新しいトピック名')).toBeDisabled()
    await userEvent.click(screen.getByRole('button', { name: '再読み込み' }))
    expect(await screen.findByLabelText('トピック名: AI')).toBeInTheDocument()
    expect(screen.getByLabelText('新しいトピック名')).not.toBeDisabled()
  })
})
