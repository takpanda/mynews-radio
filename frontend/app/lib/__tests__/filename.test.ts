import { sanitizeFilename } from '../filename'

describe('sanitizeFilename', () => {
  it('通常のタイトルはそのまま使える', () => {
    expect(sanitizeFilename('ニュース番組')).toBe('ニュース番組')
  })

  it('禁止文字をアンダースコアに置換する', () => {
    expect(sanitizeFilename('A/B:C*D?E"F<G>H|I')).toBe('A_B_C_D_E_F_G_H_I')
  })

  it('ヌル文字を除去する', () => {
    expect(sanitizeFilename('abc\0def')).toBe('abcdef')
  })

  it('連続空白を1つの空白にまとめる', () => {
    expect(sanitizeFilename('abc   def')).toBe('abc def')
  })

  it('前後の空白を除去する', () => {
    expect(sanitizeFilename('  abc  ')).toBe('abc')
  })

  it('80文字を超える場合は切り詰める', () => {
    const long = 'あ'.repeat(100)
    expect(sanitizeFilename(long).length).toBe(80)
  })

  it('全て除去対象の場合はアンダースコアになる', () => {
    expect(sanitizeFilename('\\/:*?"<>|')).toBe('_________')
  })

  it('空文字列の場合はuntitledになる', () => {
    expect(sanitizeFilename('')).toBe('untitled')
  })

  it('空白のみの場合はuntitledになる', () => {
    expect(sanitizeFilename('   ')).toBe('untitled')
  })

  it('記号を含む日本語タイトル', () => {
    expect(sanitizeFilename('「重大ニュース」速報！')).toBe('「重大ニュース」速報！')
  })

  it('「episode」はそのまま', () => {
    expect(sanitizeFilename('episode')).toBe('episode')
  })
})
