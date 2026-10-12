/**
 * TTSエンジン・ボイス設定の純粋な型・定数（BEE-1117）。
 * クライアントコンポーネントから参照されるため、next/headers や process.env などサーバー専用処理を置かないこと。
 */
export interface VoiceSettings {
  aivispeech_speaker_male: number
  aivispeech_speaker_female: number
  voicevox_speaker_male: number
  voicevox_speaker_female: number
  fishs2pro_voice_male: string
  fishs2pro_voice_female: string
}

export type VoiceEngineKey = 'aivispeech' | 'voicevox' | 'fishs2pro'
export type VoiceGender = 'male' | 'female'

export interface VoiceOption {
  display_name: string
  value: number | string
  speaker_name: string | null
  style_name: string | null
}

export interface EngineVoiceOptions {
  status: 'ok' | 'error'
  options: VoiceOption[]
  error: string | null
}

export interface VoiceOptionsResponse {
  aivispeech: EngineVoiceOptions
  voicevox: EngineVoiceOptions
  fishs2pro: EngineVoiceOptions
}

export const VOICE_ENGINES: { key: VoiceEngineKey; label: string }[] = [
  { key: 'aivispeech', label: 'AivisSpeech' },
  { key: 'voicevox', label: 'VOICEVOX' },
  { key: 'fishs2pro', label: 'Fish S2 Pro' },
]

/**
 * TTSをFish S2 Proのみに制限する対応で無効化しているエンジン（BEE-1075）。
 * 再有効化する場合はここから外す。UI・型・保存値は残したまま選択のみ止める。
 */
export const DISABLED_TTS_ENGINES: VoiceEngineKey[] = ['aivispeech', 'voicevox']
export const DISABLED_TTS_ENGINE_MESSAGE = '現在は Fish S2 Pro のみ利用できます'

export const VOICE_FIELD_MAP: Record<VoiceEngineKey, Record<VoiceGender, keyof VoiceSettings>> = {
  aivispeech: { male: 'aivispeech_speaker_male', female: 'aivispeech_speaker_female' },
  voicevox: { male: 'voicevox_speaker_male', female: 'voicevox_speaker_female' },
  fishs2pro: { male: 'fishs2pro_voice_male', female: 'fishs2pro_voice_female' },
}

/** 指定エンジンが無効化されているか。定数が欠落していても落ちないよう防御的に判定する。 */
export function isTtsDisabled(engine: VoiceEngineKey): boolean {
  return Array.isArray(DISABLED_TTS_ENGINES) && DISABLED_TTS_ENGINES.includes(engine)
}
