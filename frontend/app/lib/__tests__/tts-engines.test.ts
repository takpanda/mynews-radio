import { DISABLED_TTS_ENGINES, isTtsDisabled } from '../tts-engines'

describe('isTtsDisabled', () => {
  it('aivispeech / voicevox は無効、fishs2pro は有効', () => {
    expect(isTtsDisabled('aivispeech')).toBe(true)
    expect(isTtsDisabled('voicevox')).toBe(true)
    expect(isTtsDisabled('fishs2pro')).toBe(false)
  })

  it('DISABLED_TTS_ENGINES が定義されている', () => {
    expect(Array.isArray(DISABLED_TTS_ENGINES)).toBe(true)
  })
})
