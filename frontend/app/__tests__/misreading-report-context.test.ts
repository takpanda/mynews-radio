import {
  findCurrentLine,
  buildPlaybackReportContext,
  buildScriptLineReportContext,
  buildArticleReportContext,
} from '../lib/misreading-report-context'
import type { Script } from '../lib/api'

// ============================================================
// findCurrentLine のテスト
// ============================================================

describe('findCurrentLine', () => {
  const lines: Script['lines'] = [
    { speaker: 'male', text: '最初の行', article_id: null, section: 'intro', start_time: 0 },
    { speaker: 'female', text: '二番目の行', article_id: null, section: 'main', start_time: 10 },
    { speaker: 'male', text: '三番目の行', article_id: null, section: 'main', start_time: 20 },
  ]

  it('linesが空ならnullを返す', () => {
    expect(findCurrentLine([], 0)).toBeNull()
  })

  it('linesがnull相当ならnullを返す', () => {
    expect(findCurrentLine(null as unknown as Script['lines'], 0)).toBeNull()
  })

  it('currentTime 0でstart_time 0の行を返す', () => {
    const result = findCurrentLine(lines, 0)
    expect(result).not.toBeNull()
    expect(result!.text).toBe('最初の行')
  })

  it('currentTimeがstart_time範囲内の最新行を返す', () => {
    expect(findCurrentLine(lines, 15)!.text).toBe('二番目の行')
  })

  it('start_timeがundefinedの行をスキップする', () => {
    const withUndefined: Script['lines'] = [
      { speaker: 'male', text: '時間なし行', article_id: null, section: 'main' },
    ]
    expect(findCurrentLine(withUndefined, 0)).toBeNull()
  })
})

// ============================================================
// buildPlaybackReportContext のテスト
// ============================================================

describe('buildPlaybackReportContext', () => {
  const episode = { id: 1, audioUrl: '/audio/test.mp3' }

  const lines: Script['lines'] = [
    { speaker: 'male', text: '記事1の行', article_id: 100, section: 'news', start_time: 5 },
    { speaker: 'female', text: '記事2の行', article_id: 101, section: 'news', start_time: 20 },
    { speaker: 'male', text: '時間なし行', article_id: 102, section: 'news' },
  ]

  const items = [
    { article_id: 100, audio_generation_id: 'gen_abc_100' },
    { article_id: 101, audio_generation_id: null },
  ]

  it('script === null ならtargetSentence空＋allowEditTarget', () => {
    const ctx = buildPlaybackReportContext(episode, null, [], 30)
    expect(ctx.episodeId).toBe(1)
    expect(ctx.targetSentence).toBe('')
    expect(ctx.allowEditTarget).toBe(true)
    expect(ctx.generationId).toBeNull()
  })

  it('再生位置5で記事ID100の行を取得しgenerationIdを伝播する', () => {
    const script = { lines, title: '', date: '' }
    const ctx = buildPlaybackReportContext(episode, script, items, 5)
    expect(ctx.targetSentence).toBe('記事1の行')
    expect(ctx.articleId).toBe(100)
    expect(ctx.generationId).toBe('gen_abc_100')
    expect(ctx.allowEditTarget).toBe(false)
    expect(ctx.playbackPosition).toBe(5)
  })

  it('articleIdに紐付くitemsがない場合generationIdはnull', () => {
    const script = { lines, title: '', date: '' }
    const itemsWithNoMatch = [
      { article_id: 999, audio_generation_id: 'gen_999' },
    ]
    const ctx = buildPlaybackReportContext(episode, script, itemsWithNoMatch, 5)
    expect(ctx.generationId).toBeNull()
  })

  it('articleIdがnullの時generationIdはnull', () => {
    const linesWithNullArticle: Script['lines'] = [
      { speaker: 'male', text: '記事なし行', article_id: null, section: 'main', start_time: 0 },
    ]
    const script = { lines: linesWithNullArticle, title: '', date: '' }
    const ctx = buildPlaybackReportContext(episode, script, items, 0)
    expect(ctx.generationId).toBeNull()
  })

  it('start_time未設定の行はスキップされtargetSentence空＋allowEditTarget', () => {
    const linesWithUndefined: Script['lines'] = [
      { speaker: 'male', text: '時間なし行', article_id: null, section: 'main' },
    ]
    const script = { lines: linesWithUndefined, title: '', date: '' }
    const ctx = buildPlaybackReportContext(episode, script, [], 0)
    expect(ctx.targetSentence).toBe('')
    expect(ctx.allowEditTarget).toBe(true)
    expect(ctx.playbackPosition).toBeNull()
  })

  it('currentTimeが0以下ならplaybackPositionはnull', () => {
    const script = { lines, title: '', date: '' }
    const ctx = buildPlaybackReportContext(episode, script, items, 0)
    expect(ctx.playbackPosition).toBeNull()
  })
})

// ============================================================
// buildScriptLineReportContext のテスト
// ============================================================

describe('buildScriptLineReportContext', () => {
  it('行のテキストをtargetSentenceに設定しallowEditTargetはtrue', () => {
    const line = { speaker: 'male' as const, text: 'この行を報告', article_id: 100, section: 'news', start_time: 5 }
    const ctx = buildScriptLineReportContext(1, line)
    expect(ctx.episodeId).toBe(1)
    expect(ctx.targetSentence).toBe('この行を報告')
    expect(ctx.allowEditTarget).toBe(true)
    expect(ctx.articleId).toBe(100)
    expect(ctx.generationId).toBeNull()
    expect(ctx.playbackPosition).toBeNull()
  })

  it('article_idがnullでも動作する', () => {
    const line = { speaker: 'female' as const, text: '記事なし行', article_id: null, section: 'intro' }
    const ctx = buildScriptLineReportContext(99, line)
    expect(ctx.episodeId).toBe(99)
    expect(ctx.targetSentence).toBe('記事なし行')
    expect(ctx.articleId).toBeNull()
  })

  it('needsGenerationIdは未設定（再生経路と異なり音声生成IDを要求しない）', () => {
    const line = { speaker: 'male' as const, text: '台本行', article_id: null, section: 'news' }
    const ctx = buildScriptLineReportContext(1, line)
    expect(ctx.needsGenerationId).toBeUndefined()
  })
})

// ============================================================
// buildArticleReportContext のテスト
// ============================================================

describe('buildArticleReportContext', () => {
  it('itemsからgenerationIdを伝播する', () => {
    const items = [
      { article_id: 100, audio_generation_id: 'gen_abc_100' },
    ]
    const ctx = buildArticleReportContext(1, 100, items)
    expect(ctx.episodeId).toBe(1)
    expect(ctx.articleId).toBe(100)
    expect(ctx.generationId).toBe('gen_abc_100')
    expect(ctx.allowEditTarget).toBe(true)
    expect(ctx.targetSentence).toBe('')
  })

  it('itemsにarticle_idが存在しない場合generationIdはnull', () => {
    const items = [
      { article_id: 999, audio_generation_id: 'gen_999' },
    ]
    const ctx = buildArticleReportContext(1, 100, items)
    expect(ctx.generationId).toBeNull()
  })

  it('itemsが空配列ならgenerationIdはnull', () => {
    const ctx = buildArticleReportContext(1, 100, [])
    expect(ctx.generationId).toBeNull()
  })

  it('audio_generation_idがundefinedの項目はnull', () => {
    const items = [
      { article_id: 100 } as { article_id: number; audio_generation_id?: string },
    ]
    const ctx = buildArticleReportContext(1, 100, items)
    expect(ctx.generationId).toBeNull()
  })
})
