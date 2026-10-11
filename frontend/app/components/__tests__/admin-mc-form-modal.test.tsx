import '@testing-library/jest-dom'

import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import AdminMcFormModal from '../AdminMcFormModal'
import { DISABLED_TTS_ENGINE_MESSAGE } from '../../lib/admin-voice-settings'
import type { Mc } from '../../lib/admin-programs'

const mockCreateMc = jest.fn()
const mockReplaceMc = jest.fn()

jest.mock('../../lib/admin-programs', () => ({
  ...jest.requireActual('../../lib/admin-programs'),
  createMc: (...args: unknown[]) => mockCreateMc(...args),
  replaceMc: (...args: unknown[]) => mockReplaceMc(...args),
}))

const mockFetchVoiceOptions = jest.fn()

jest.mock('../../lib/admin-voice-settings', () => ({
  ...jest.requireActual('../../lib/admin-voice-settings'),
  fetchVoiceOptionsClient: () => mockFetchVoiceOptions(),
}))

const FISH_VOICES = ['male', 'female', 'morigawa', 'ando_momo', 'watanabe_rumi', 'tahara_momoko', 'yamamoto_yukino', 'ejima_aeri']
const opts = (values: (string | number)[]) => ({
  status: 'ok',
  error: null,
  options: values.map((v) => ({ display_name: String(v), value: v, speaker_name: null, style_name: null })),
})
const voiceOptionsOk = () => ({
  aivispeech: opts([]),
  voicevox: opts([]),
  fishs2pro: opts(FISH_VOICES),
})

const existingMc: Mc = {
  id: 'radio_male',
  name: '田村',
  role: 'メインMC',
  voice_fishs2pro: 'male',
  voice_aivispeech: 1310138976,
  voice_voicevox: 11,
  is_active: true,
  created_at: '',
  updated_at: '',
}

beforeEach(() => {
  jest.clearAllMocks()
  mockFetchVoiceOptions.mockResolvedValue(voiceOptionsOk())
})

describe('AdminMcFormModal', () => {
  const fish = () => screen.getByLabelText('Fish S2 Pro') as HTMLSelectElement

  it('3つの音声入力がselectで、Fishの候補はAPIの応答件数ぶん表示される', async () => {
    render(<AdminMcFormModal mc={null} onClose={jest.fn()} onSuccess={jest.fn()} />)
    await waitFor(() => expect(fish().options).toHaveLength(FISH_VOICES.length + 1))
    expect(screen.getByLabelText('AivisSpeech').tagName).toBe('SELECT')
    expect(screen.getByLabelText('VOICEVOX').tagName).toBe('SELECT')
    expect(fish().options[0]).toHaveTextContent('選択してください')
    expect(Array.from(fish().options).slice(1).map((o) => o.value)).toEqual(FISH_VOICES)
  })

  it('候補の件数はAPI応答に従う（コードで固定しない）', async () => {
    mockFetchVoiceOptions.mockResolvedValue({ ...voiceOptionsOk(), fishs2pro: opts(['a', 'b']) })
    render(<AdminMcFormModal mc={null} onClose={jest.fn()} onSuccess={jest.fn()} />)
    await waitFor(() => expect(fish().options).toHaveLength(3))
  })

  it('編集時は保存済みの値が取得後に初期選択され、nullは空選択肢になる', async () => {
    const { unmount } = render(<AdminMcFormModal mc={existingMc} onClose={jest.fn()} onSuccess={jest.fn()} />)
    await waitFor(() => expect(fish().value).toBe('male'))
    unmount()
    render(<AdminMcFormModal mc={{ ...existingMc, voice_fishs2pro: null }} onClose={jest.fn()} onSuccess={jest.fn()} />)
    await waitFor(() => expect(fish().options).toHaveLength(FISH_VOICES.length + 1))
    expect(fish().value).toBe('')
  })

  it('AivisSpeech・VOICEVOXは無効化され、ツールチップで案内が表示される', async () => {
    render(<AdminMcFormModal mc={existingMc} onClose={jest.fn()} onSuccess={jest.fn()} />)
    await waitFor(() => expect(fish().options.length).toBeGreaterThan(1))
    expect(fish()).not.toBeDisabled()
    for (const label of ['AivisSpeech', 'VOICEVOX']) {
      const el = screen.getByLabelText(label)
      expect(el).toBeDisabled()
      expect(el).toHaveAttribute('title', DISABLED_TTS_ENGINE_MESSAGE)
    }
    expect(screen.getByText(DISABLED_TTS_ENGINE_MESSAGE)).toBeInTheDocument()
  })

  it('保存すると無効化されたAivisSpeech・VOICEVOXの値もそのまま送信される', async () => {
    mockReplaceMc.mockResolvedValueOnce({ ...existingMc })
    const user = userEvent.setup()
    render(<AdminMcFormModal mc={existingMc} onClose={jest.fn()} onSuccess={jest.fn()} />)
    await waitFor(() => expect(fish().value).toBe('male'))

    await user.click(screen.getByRole('button', { name: '保存する' }))

    expect(mockReplaceMc).toHaveBeenCalledWith(
      'radio_male',
      expect.objectContaining({ voice_aivispeech: 1310138976, voice_voicevox: 11, voice_fishs2pro: 'male' }),
    )
  })

  it('追加時にFishを選択して保存でき、未選択ならnullで送信される', async () => {
    mockCreateMc.mockResolvedValue({ ...existingMc })
    const user = userEvent.setup()
    render(<AdminMcFormModal mc={null} onClose={jest.fn()} onSuccess={jest.fn()} />)
    await waitFor(() => expect(fish().options.length).toBeGreaterThan(1))
    await user.type(screen.getByPlaceholderText('例: radio_male'), 'mc1')
    await user.click(screen.getByRole('button', { name: '追加する' }))
    expect(mockCreateMc).toHaveBeenLastCalledWith(
      expect.objectContaining({ voice_fishs2pro: null, voice_aivispeech: null, voice_voicevox: null }),
    )

    await user.selectOptions(fish(), 'morigawa')
    await user.click(screen.getByRole('button', { name: '追加する' }))
    expect(mockCreateMc).toHaveBeenLastCalledWith(expect.objectContaining({ voice_fishs2pro: 'morigawa' }))
  })

  it('候補取得に失敗してもモーダルは表示されエラーが出る。取得だけでは保存値を書き換えない', async () => {
    mockFetchVoiceOptions.mockRejectedValue(new Error('タイムアウトしました'))
    mockReplaceMc.mockResolvedValueOnce({ ...existingMc })
    const user = userEvent.setup()
    render(<AdminMcFormModal mc={existingMc} onClose={jest.fn()} onSuccess={jest.fn()} />)

    expect(await screen.findByRole('alert')).toHaveTextContent('タイムアウトしました')
    expect(screen.getByRole('dialog')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: '保存する' }))
    expect(mockReplaceMc).toHaveBeenCalledWith(
      'radio_male',
      expect.objectContaining({ voice_fishs2pro: 'male', voice_aivispeech: 1310138976, voice_voicevox: 11 }),
    )
  })

  describe('候補にない保存済みの値', () => {
    const outMc: Mc = { ...existingMc, voice_fishs2pro: 'old_voice' }
    const sel = (l: string) => screen.getByLabelText(l) as HTMLSelectElement

    it('候補外の値は「現在の値: xxx（候補にありません）」で表示・選択され、無効エンジンはdisabledのまま', async () => {
      render(<AdminMcFormModal mc={outMc} onClose={jest.fn()} onSuccess={jest.fn()} />)
      await waitFor(() => expect(fish().options.length).toBeGreaterThan(2))
      expect(fish().value).toBe('old_voice')
      expect(fish().selectedOptions[0]).toHaveTextContent('現在の値: old_voice（候補にありません）')
      expect(sel('AivisSpeech').value).toBe('1310138976')
      expect(sel('AivisSpeech').selectedOptions[0]).toHaveTextContent('現在の値: 1310138976（候補にありません）')
      expect(sel('VOICEVOX').value).toBe('11')
      expect(sel('AivisSpeech')).toBeDisabled()
      expect(sel('VOICEVOX')).toBeDisabled()
    })

    it('候補に同じIDがある場合は通常optionに一致し、重複optionを作らない', async () => {
      render(<AdminMcFormModal mc={existingMc} onClose={jest.fn()} onSuccess={jest.fn()} />)
      await waitFor(() => expect(fish().options).toHaveLength(FISH_VOICES.length + 1))
      expect(fish().value).toBe('male')
      expect(Array.from(fish().options).filter((o) => o.value === 'male')).toHaveLength(1)
    })

    it('取得失敗でも既存値を表示・保持して保存でき、エラー表示も維持される', async () => {
      mockFetchVoiceOptions.mockRejectedValue(new Error('504'))
      mockReplaceMc.mockResolvedValueOnce({ ...outMc })
      const user = userEvent.setup()
      render(<AdminMcFormModal mc={outMc} onClose={jest.fn()} onSuccess={jest.fn()} />)
      expect(await screen.findByRole('alert')).toHaveTextContent('504')
      expect(fish().value).toBe('old_voice')
      expect(fish().selectedOptions[0]).toHaveTextContent('old_voice')
      expect(fish().selectedOptions[0]).not.toHaveTextContent('候補にありません')
      await user.click(screen.getByRole('button', { name: '保存する' }))
      expect(mockReplaceMc).toHaveBeenCalledWith(
        'radio_male',
        expect.objectContaining({ voice_fishs2pro: 'old_voice', voice_aivispeech: 1310138976, voice_voicevox: 11 }),
      )
    })

    it('HTTP成功でもFishがstatus:errorなら既存値を表示・保持し、候補外とは断定せずエラーを表示する', async () => {
      mockFetchVoiceOptions.mockResolvedValue({
        ...voiceOptionsOk(),
        fishs2pro: { status: 'error', error: 'fish unavailable', options: [] },
      })
      mockReplaceMc.mockResolvedValueOnce({ ...outMc })
      const user = userEvent.setup()
      render(<AdminMcFormModal mc={outMc} onClose={jest.fn()} onSuccess={jest.fn()} />)
      expect(await screen.findByRole('alert')).toHaveTextContent('fish unavailable')
      expect(fish().value).toBe('old_voice')
      expect(fish().selectedOptions[0]).toHaveTextContent('old_voice')
      expect(fish().selectedOptions[0]).not.toHaveTextContent('候補にありません')
      await user.click(screen.getByRole('button', { name: '保存する' }))
      expect(mockReplaceMc).toHaveBeenCalledWith(
        'radio_male',
        expect.objectContaining({ voice_fishs2pro: 'old_voice' }),
      )
    })

    it('候補外の値から別候補・空選択へ変更でき、その値で保存される', async () => {
      mockReplaceMc.mockResolvedValue({ ...outMc })
      const user = userEvent.setup()
      render(<AdminMcFormModal mc={outMc} onClose={jest.fn()} onSuccess={jest.fn()} />)
      await waitFor(() => expect(fish().options.length).toBeGreaterThan(2))
      await user.selectOptions(fish(), 'female')
      await user.click(screen.getByRole('button', { name: '保存する' }))
      expect(mockReplaceMc).toHaveBeenLastCalledWith('radio_male', expect.objectContaining({ voice_fishs2pro: 'female' }))
      await user.selectOptions(fish(), '')
      await user.click(screen.getByRole('button', { name: '保存する' }))
      expect(mockReplaceMc).toHaveBeenLastCalledWith('radio_male', expect.objectContaining({ voice_fishs2pro: null }))
    })

    it('候補空配列でも数値エンジンの既存値を保持して保存される', async () => {
      mockReplaceMc.mockResolvedValue({ ...outMc })
      const user = userEvent.setup()
      render(<AdminMcFormModal mc={{ ...existingMc, voice_aivispeech: null }} onClose={jest.fn()} onSuccess={jest.fn()} />)
      await waitFor(() => expect(fish().value).toBe('male'))
      expect(sel('AivisSpeech').value).toBe('')
      await user.click(screen.getByRole('button', { name: '保存する' }))
      expect(mockReplaceMc).toHaveBeenCalledWith('radio_male', expect.objectContaining({ voice_aivispeech: null, voice_voicevox: 11 }))
    })
  })
})
