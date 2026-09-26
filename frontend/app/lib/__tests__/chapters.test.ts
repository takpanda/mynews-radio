import { buildChapters } from '../chapters'
import type { Script } from '../api'

function makeScript(overrides: Partial<Script>): Script {
  return { title: 'タイトル', lines: [], ...overrides }
}

describe('buildChapters', () => {
  it('scriptがnullの場合は空配列を返す', () => {
    expect(buildChapters(null)).toEqual([])
  })

  describe('旧台本（segments情報なし）', () => {
    it('sectionごとに章を作り、つなぎと再登場を除外する', () => {
      const script = makeScript({
        lines: [
          { speaker: 'male', text: 'オープニング', article_id: null, section: 'intro', start_time: 0 },
          { speaker: 'female', text: 'つなぎ', article_id: null, section: 'transition', start_time: 5 },
          { speaker: 'male', text: 'ニュース1', article_id: null, section: 'news', start_time: 10 },
          { speaker: 'female', text: 'ニュース2', article_id: null, section: 'news', start_time: 20 },
          { speaker: 'male', text: 'エンディング', article_id: null, section: 'outro', start_time: 30 },
        ],
      })

      expect(buildChapters(script)).toEqual([
        { label: 'オープニング', startTime: 0 },
        { label: 'ニュース', startTime: 10 },
        { label: 'エンディング', startTime: 30 },
      ])
    })

    it('章が1件以下になる場合は空配列を返す', () => {
      const script = makeScript({
        lines: [{ speaker: 'male', text: 'オープニングのみ', article_id: null, section: 'intro', start_time: 0 }],
      })
      expect(buildChapters(script)).toEqual([])
    })

    it('start_timeが無い行からは章を作らない', () => {
      const script = makeScript({
        lines: [
          { speaker: 'male', text: 'オープニング', article_id: null, section: 'intro', start_time: 0 },
          { speaker: 'female', text: 'ニュース', article_id: null, section: 'news' },
          { speaker: 'male', text: 'エンディング', article_id: null, section: 'outro', start_time: 30 },
        ],
      })
      // newsはstart_timeが無いため章にならず、残り2件で章が成立する
      expect(buildChapters(script)).toEqual([
        { label: 'オープニング', startTime: 0 },
        { label: 'エンディング', startTime: 30 },
      ])
    })
  })

  describe('新台本（segments情報あり）', () => {
    it('segment IDごとに章を作り、保存済みlabelを使う', () => {
      const script = makeScript({
        segments: [
          { id: 'headline_open', label: 'ヘッドライン 1' },
          { id: 'headline_wrap', label: 'ヘッドライン 2' },
        ],
        lines: [
          { speaker: 'host', text: '前半headline', article_id: null, section: 'headline', segment: 'headline_open', start_time: 0 },
          { speaker: 'host', text: '後半headline', article_id: null, section: 'headline', segment: 'headline_wrap', start_time: 15 },
        ],
      })

      expect(buildChapters(script)).toEqual([
        { label: 'ヘッドライン 1', startTime: 0 },
        { label: 'ヘッドライン 2', startTime: 15 },
      ])
    })

    it('同じkindでも異なるsegment IDは別チャプターとして扱う', () => {
      const script = makeScript({
        segments: [
          { id: 'news_a', label: 'ニュースA' },
          { id: 'news_b', label: 'ニュースB' },
        ],
        lines: [
          { speaker: 'host', text: 'ニュースAの内容', article_id: null, section: 'news', segment: 'news_a', start_time: 0 },
          { speaker: 'host', text: 'ニュースBの内容', article_id: null, section: 'news', segment: 'news_b', start_time: 10 },
        ],
      })

      expect(buildChapters(script)).toEqual([
        { label: 'ニュースA', startTime: 0 },
        { label: 'ニュースB', startTime: 10 },
      ])
    })

    it('同じsegment IDが再登場した場合はスキップする', () => {
      const script = makeScript({
        segments: [
          { id: 'news_a', label: 'ニュースA' },
          { id: 'news_b', label: 'ニュースB' },
        ],
        lines: [
          { speaker: 'host', text: 'ニュースA-1', article_id: null, section: 'news', segment: 'news_a', start_time: 0 },
          { speaker: 'host', text: 'ニュースA-2', article_id: null, section: 'news', segment: 'news_a', start_time: 5 },
          { speaker: 'host', text: 'ニュースB', article_id: null, section: 'news', segment: 'news_b', start_time: 10 },
        ],
      })

      expect(buildChapters(script)).toEqual([
        { label: 'ニュースA', startTime: 0 },
        { label: 'ニュースB', startTime: 10 },
      ])
    })

    it('transition kindのsegmentは章にしない', () => {
      const script = makeScript({
        segments: [
          { id: 'intro_a', label: 'オープニング' },
          { id: 'bridge', label: 'つなぎ' },
          { id: 'outro_a', label: 'エンディング' },
        ],
        lines: [
          { speaker: 'host', text: 'オープニング', article_id: null, section: 'intro', segment: 'intro_a', start_time: 0 },
          { speaker: 'host', text: 'つなぎ', article_id: null, section: 'transition', segment: 'bridge', start_time: 5 },
          { speaker: 'host', text: 'エンディング', article_id: null, section: 'outro', segment: 'outro_a', start_time: 10 },
        ],
      })

      expect(buildChapters(script)).toEqual([
        { label: 'オープニング', startTime: 0 },
        { label: 'エンディング', startTime: 10 },
      ])
    })

    it('segments一覧に該当labelが無い場合はsection名にフォールバックする', () => {
      const script = makeScript({
        segments: [{ id: 'news_a', label: 'ニュースA' }],
        lines: [
          { speaker: 'host', text: 'ニュースA', article_id: null, section: 'news', segment: 'news_a', start_time: 0 },
          { speaker: 'host', text: '未知のsegment', article_id: null, section: 'discussion', segment: 'unknown_id', start_time: 10 },
        ],
      })

      expect(buildChapters(script)).toEqual([
        { label: 'ニュースA', startTime: 0 },
        { label: '討論', startTime: 10 },
      ])
    })
  })
})
