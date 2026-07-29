import '@testing-library/jest-dom'

import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import SynthesizeAudioButton from '../SynthesizeAudioButton'

const mockSynthesize = jest.fn()
const mockRefresh = jest.fn()

class TestTextDecoder {
  decode(value?: Uint8Array): string {
    return String.fromCharCode(...Array.from(value ?? []))
  }
}

Object.defineProperty(globalThis, 'TextDecoder', { value: TestTextDecoder, configurable: true })

jest.mock('../../lib/api', () => ({
  synthesizeEpisodeStream: (...args: unknown[]) => mockSynthesize(...args),
}))

jest.mock('next/navigation', () => ({
  useRouter: () => ({ refresh: mockRefresh }),
}))

function sseResponse(payload: object, event = 'progress'): Response {
  const text = `event: ${event}\ndata: ${JSON.stringify(payload)}\n\n`
  const chunk = Uint8Array.from(Array.from(text).map((character) => character.charCodeAt(0)))
  const reader = {
    read: jest.fn()
      .mockResolvedValueOnce({ done: false, value: chunk })
      .mockResolvedValueOnce({ done: true, value: undefined }),
  }
  return { ok: true, status: 200, body: { getReader: () => reader } } as unknown as Response
}

describe('SynthesizeAudioButton', () => {
  beforeEach(() => {
    jest.clearAllMocks()
  })

  it('実行中ジョブの同一キー再送後にローディングを解除して再確認状態へ遷移する', async () => {
    mockSynthesize.mockResolvedValue(sseResponse({
      phase: 'synthesize',
      status: 'running',
      reused: true,
      message: 'Existing synthesis job is still running',
    }))
    const user = userEvent.setup()
    const { container } = render(<SynthesizeAudioButton episodeId={42} />)

    await user.click(screen.getByRole('button', { name: '音声ファイルを作成する' }))

    expect(await screen.findByText('音声合成は既に実行中です。完了後に状態を再確認してください。')).toBeInTheDocument()
    expect(screen.queryByText('音声を合成しています...')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: '状態を再確認' })).toBeInTheDocument()
    expect(container.querySelector('.animate-spin')).not.toBeInTheDocument()
  })

  it('SSE error確定後は冪等キーを解放し、再試行でキーを差し替える', async () => {
    mockSynthesize
      .mockResolvedValueOnce(sseResponse({ message: 'failed' }, 'error'))
      .mockResolvedValueOnce(sseResponse({ status: 'complete' }, 'complete'))
    const user = userEvent.setup()
    render(<SynthesizeAudioButton episodeId={42} />)

    await user.click(screen.getByRole('button', { name: '音声ファイルを作成する' }))
    expect(await screen.findByRole('button', { name: '再試行' })).toBeInTheDocument()
    const firstKey = mockSynthesize.mock.calls[0][2]
    expect(firstKey).toEqual(expect.any(String))

    await user.click(screen.getByRole('button', { name: '再試行' }))
    await screen.findByText('音声が完成しました')
    const secondKey = mockSynthesize.mock.calls[1][2]
    expect(secondKey).toEqual(expect.any(String))
    expect(secondKey).not.toBe(firstKey)
  })
})
