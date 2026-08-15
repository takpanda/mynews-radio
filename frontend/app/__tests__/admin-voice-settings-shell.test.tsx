import '@testing-library/jest-dom'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import AdminVoiceSettingsShell from '../components/AdminVoiceSettingsShell'
import type { VoiceOptionsResponse, VoiceSettings } from '../lib/admin-voice-settings'

const mockFetchOptions = jest.fn()
const mockSave = jest.fn()
jest.mock('../lib/admin-voice-settings', () => {
  const actual = jest.requireActual('../lib/admin-voice-settings')
  return {
    ...actual,
    fetchVoiceOptionsClient: (...args: unknown[]) => mockFetchOptions(...args),
    saveVoiceSettingsClient: (...args: unknown[]) => mockSave(...args),
  }
})

const sampleSettings: VoiceSettings = {
  aivispeech_speaker_male: 1310138976,
  aivispeech_speaker_female: 1388823424,
  voicevox_speaker_male: 11,
  voicevox_speaker_female: 2,
  fishs2pro_voice_male: 'male',
  fishs2pro_voice_female: 'morigawa',
}

const sampleOptions: VoiceOptionsResponse = {
  aivispeech: {
    status: 'ok',
    error: null,
    options: [
      { display_name: '阿井田 茂 - ノーマル', value: 1310138976, speaker_name: '阿井田 茂', style_name: 'ノーマル' },
      { display_name: '結月ゆかり - ノーマル', value: 1388823424, speaker_name: '結月ゆかり', style_name: 'ノーマル' },
    ],
  },
  voicevox: {
    status: 'ok',
    error: null,
    options: [
      { display_name: '四国めたん - ノーマル', value: 11, speaker_name: '四国めたん', style_name: 'ノーマル' },
      { display_name: 'ずんだもん - ノーマル', value: 2, speaker_name: 'ずんだもん', style_name: 'ノーマル' },
    ],
  },
  fishs2pro: {
    status: 'ok',
    error: null,
    options: [
      { display_name: 'male', value: 'male', speaker_name: null, style_name: null },
      { display_name: 'morigawa', value: 'morigawa', speaker_name: null, style_name: null },
    ],
  },
}

function clone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value))
}

beforeEach(() => {
  jest.clearAllMocks()
})

describe('AdminVoiceSettingsShell', () => {
  it('正常系：3エンジン分の男声・女声が現在値で選択表示される', () => {
    render(<AdminVoiceSettingsShell initialSettings={sampleSettings} initialOptions={sampleOptions} />)
    expect(screen.getByText('ボイス設定')).toBeInTheDocument()
    expect(screen.getByText('AivisSpeech')).toBeInTheDocument()
    expect(screen.getByText('VOICEVOX')).toBeInTheDocument()
    expect(screen.getByText('Fish S2 Pro')).toBeInTheDocument()
    expect(screen.getAllByText('男声')).toHaveLength(3)
    expect(screen.getAllByText('女声')).toHaveLength(3)
  })

  it('各コンボボックスに現在の保存値が初期選択される', () => {
    render(<AdminVoiceSettingsShell initialSettings={sampleSettings} initialOptions={sampleOptions} />)
    const select = screen.getByDisplayValue('阿井田 茂 - ノーマル') as HTMLSelectElement
    expect(select.value).toBe('1310138976')
  })

  it('保存成功：保存後の反映説明が表示される', async () => {
    mockSave.mockResolvedValueOnce(sampleSettings)
    const user = userEvent.setup()
    render(<AdminVoiceSettingsShell initialSettings={sampleSettings} initialOptions={sampleOptions} />)

    await user.click(screen.getByRole('button', { name: '保存' }))

    await waitFor(() => {
      expect(screen.getByText(/保存しました。保存後に開始する生成から反映されます。/)).toBeInTheDocument()
    })
    expect(mockSave).toHaveBeenCalledTimes(1)
  })

  it('保存失敗：エラーメッセージが表示され値は保持される', async () => {
    mockSave.mockRejectedValueOnce(new Error('入力内容を確認してください。'))
    const user = userEvent.setup()
    render(<AdminVoiceSettingsShell initialSettings={sampleSettings} initialOptions={sampleOptions} />)

    await user.click(screen.getByRole('button', { name: '保存' }))

    await waitFor(() => {
      expect(screen.getByText('入力内容を確認してください。')).toBeInTheDocument()
    })
    const select = screen.getByDisplayValue('阿井田 茂 - ノーマル') as HTMLSelectElement
    expect(select.value).toBe('1310138976')
  })

  it('二重送信防止：保存中は保存ボタンが無効化され1回しか呼ばれない', async () => {
    let resolveSave: (value: VoiceSettings) => void = () => {}
    mockSave.mockImplementationOnce(
      () => new Promise<VoiceSettings>((resolve) => { resolveSave = resolve }),
    )
    const user = userEvent.setup()
    render(<AdminVoiceSettingsShell initialSettings={sampleSettings} initialOptions={sampleOptions} />)

    const button = screen.getByRole('button', { name: '保存' })
    await user.click(button)
    expect(screen.getByRole('button', { name: '保存中…' })).toBeDisabled()

    await user.click(button)
    expect(mockSave).toHaveBeenCalledTimes(1)

    resolveSave(sampleSettings)
    await waitFor(() => expect(screen.getByRole('button', { name: '保存' })).not.toBeDisabled())
  })

  it('一覧取得の一部失敗：対象エンジンにエラーと再試行ボタンが表示され、他エンジンは操作できる', () => {
    const partial = clone(sampleOptions)
    partial.voicevox = { status: 'error', options: [], error: '話者一覧を取得できませんでした' }
    render(<AdminVoiceSettingsShell initialSettings={sampleSettings} initialOptions={partial} />)

    expect(screen.getByText('話者一覧を取得できませんでした')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '再試行' })).toBeInTheDocument()

    const aivisSelect = screen.getByDisplayValue('阿井田 茂 - ノーマル') as HTMLSelectElement
    expect(aivisSelect).not.toBeDisabled()
  })

  it('一覧取得の失敗エンジンのコンボボックスは無効化される', () => {
    const partial = clone(sampleOptions)
    partial.voicevox = { status: 'error', options: [], error: '話者一覧を取得できませんでした' }
    render(<AdminVoiceSettingsShell initialSettings={sampleSettings} initialOptions={partial} />)

    const voicevoxSelect = screen.getByDisplayValue('11') as HTMLSelectElement
    expect(voicevoxSelect).toBeDisabled()
  })

  it('再試行成功：一覧が再取得されエラー表示が消える', async () => {
    const partial = clone(sampleOptions)
    partial.voicevox = { status: 'error', options: [], error: '話者一覧を取得できませんでした' }
    mockFetchOptions.mockResolvedValueOnce(sampleOptions)
    const user = userEvent.setup()
    render(<AdminVoiceSettingsShell initialSettings={sampleSettings} initialOptions={partial} />)

    await user.click(screen.getByRole('button', { name: '再試行' }))

    await waitFor(() => {
      expect(screen.queryByText('話者一覧を取得できませんでした')).not.toBeInTheDocument()
    })
    expect(mockFetchOptions).toHaveBeenCalledTimes(1)
  })

  it('現在値欠落：一覧にない現在値は消去されず識別できる', () => {
    const settingsWithStale: VoiceSettings = { ...sampleSettings, voicevox_speaker_male: 999 }
    render(<AdminVoiceSettingsShell initialSettings={settingsWithStale} initialOptions={sampleOptions} />)

    const select = screen.getByDisplayValue('999（一覧にありません）') as HTMLSelectElement
    expect(select.value).toBe('999')
    expect(screen.getByText('現在の値は最新の一覧にありません')).toBeInTheDocument()
  })
})
