import '@testing-library/jest-dom'

import { render, screen } from '@testing-library/react'
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
})

describe('AdminMcFormModal', () => {
  it('AivisSpeech・VOICEVOXの入力は無効化され、ツールチップで案内が表示される', () => {
    render(<AdminMcFormModal mc={existingMc} onClose={jest.fn()} onSuccess={jest.fn()} />)

    const fishInput = screen.getByDisplayValue('male') as HTMLInputElement
    expect(fishInput).not.toBeDisabled()

    const aivisSpeechInput = screen.getByDisplayValue('1310138976') as HTMLInputElement
    const voicevoxInput = screen.getByDisplayValue('11') as HTMLInputElement
    expect(aivisSpeechInput).toBeDisabled()
    expect(aivisSpeechInput).toHaveAttribute('title', DISABLED_TTS_ENGINE_MESSAGE)
    expect(voicevoxInput).toBeDisabled()
    expect(voicevoxInput).toHaveAttribute('title', DISABLED_TTS_ENGINE_MESSAGE)

    expect(screen.getByText(DISABLED_TTS_ENGINE_MESSAGE)).toBeInTheDocument()
  })

  it('保存すると無効化されたAivisSpeech・VOICEVOXの値もそのまま送信される', async () => {
    mockReplaceMc.mockResolvedValueOnce({ ...existingMc })
    const user = userEvent.setup()
    render(<AdminMcFormModal mc={existingMc} onClose={jest.fn()} onSuccess={jest.fn()} />)

    await user.click(screen.getByRole('button', { name: '保存する' }))

    expect(mockReplaceMc).toHaveBeenCalledWith(
      'radio_male',
      expect.objectContaining({
        voice_aivispeech: 1310138976,
        voice_voicevox: 11,
        voice_fishs2pro: 'male',
      }),
    )
  })
})
