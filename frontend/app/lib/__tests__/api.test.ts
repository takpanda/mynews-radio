import { formatGeneratedAt } from '../api'

describe('formatGeneratedAt', () => {
  it('UTC 13:00 → JST 22:00 に変換される', () => {
    const result = formatGeneratedAt('2026-07-23T13:00:00Z')
    expect(result).toMatch(/2026\/07\/23 22:00/)
  })

  it('UTC 0:00 → JST 9:00 に変換される（日付跨ぎなし）', () => {
    const result = formatGeneratedAt('2026-01-15T00:00:00Z')
    expect(result).toMatch(/2026\/01\/15 0?9:00/)
  })

  it('UTC 23:00 → JST 翌日 8:00 に変換される（日付跨ぎ）', () => {
    const result = formatGeneratedAt('2026-06-01T23:00:00Z')
    expect(result).toMatch(/2026\/06\/02 0?8:00/)
  })

  it('出力書式が YYYY/MM/DD HH:mm の形式である', () => {
    const result = formatGeneratedAt('2026-12-31T15:30:00Z')
    expect(result).toMatch(/^\d{4}\/\d{2}\/\d{2} \d{2}:\d{2}$/)
  })

  it('分の値が正しく保持される', () => {
    const result = formatGeneratedAt('2026-03-15T07:45:00Z')
    expect(result).toMatch(/:45$/)
  })
})
