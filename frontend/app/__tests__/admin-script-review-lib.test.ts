import {
  buildSpeakerOptions,
  clearDraftFromStorage,
  collectSpeakerKeys,
  diffScriptLines,
  initialSpeakerKey,
  isSpeakerOutsideCast,
  loadDraftFromStorage,
  previewAudioClient,
  saveDraftToStorage,
  saveScriptClient,
  shouldShowSpeakerSelect,
  approveScriptClient,
  ScriptApiError,
  ScriptRevisionConflictError,
  ScriptValidationBlockedError,
  type AdminScriptReviewCastMember,
  type AdminScriptReviewLine,
} from '../lib/admin-script-review'

function line(overrides: Partial<AdminScriptReviewLine> = {}): AdminScriptReviewLine {
  return { speaker: 'male', section: 'news', text: 'テキスト', ...overrides }
}

function cast(overrides: Partial<AdminScriptReviewCastMember>[] = []): AdminScriptReviewCastMember[] {
  return overrides.map((o, i) => ({ key: `cast${i}`, name: `出演者${i}`, ...o }))
}

describe('collectSpeakerKeys', () => {
  it('登場順・重複なしでspeaker keyを返す', () => {
    const lines = [line({ speaker: 'male' }), line({ speaker: 'female' }), line({ speaker: 'male' })]
    expect(collectSpeakerKeys(lines)).toEqual(['male', 'female'])
  })

  it('1種類しかない場合は1件のみ返す', () => {
    expect(collectSpeakerKeys([line({ speaker: 'male' }), line({ speaker: 'male' })])).toEqual(['male'])
  })
})

describe('buildSpeakerOptions', () => {
  it('castがあれば台本に登場しない出演者も候補に含める', () => {
    const members = cast([{ key: 'mc-a', name: '田中' }, { key: 'mc-b', name: '鈴木' }])
    const lines = [line({ speaker: 'mc-a' })]
    expect(buildSpeakerOptions(members, lines)).toEqual([
      { key: 'mc-a', label: '田中' },
      { key: 'mc-b', label: '鈴木' },
    ])
  })

  it('cast外のspeaker keyを持つ行があれば、元のkeyを表示名にした候補を追加する', () => {
    const members = cast([{ key: 'mc-a', name: '田中' }])
    const lines = [line({ speaker: 'mc-a' }), line({ speaker: 'legacy-key' })]
    expect(buildSpeakerOptions(members, lines)).toEqual([
      { key: 'mc-a', label: '田中' },
      { key: 'legacy-key', label: 'legacy-key' },
    ])
  })

  it('castが無い場合は台本に登場するspeaker keyから候補を作る', () => {
    const lines = [line({ speaker: 'male' }), line({ speaker: 'female' })]
    expect(buildSpeakerOptions(null, lines)).toEqual([
      { key: 'male', label: 'male' },
      { key: 'female', label: 'female' },
    ])
  })

  it('castが空配列の場合も台本由来にフォールバックする', () => {
    const lines = [line({ speaker: 'male' })]
    expect(buildSpeakerOptions([], lines)).toEqual([{ key: 'male', label: 'male' }])
  })
})

describe('shouldShowSpeakerSelect', () => {
  it('castが2人なら台本に1人しか登場しなくても表示する', () => {
    const members = cast([{ key: 'mc-a' }, { key: 'mc-b' }])
    expect(shouldShowSpeakerSelect(members, [line({ speaker: 'mc-a' })])).toBe(true)
  })

  it('castが1人なら台本に別keyの行があっても表示しない', () => {
    const members = cast([{ key: 'mc-a' }])
    expect(shouldShowSpeakerSelect(members, [line({ speaker: 'mc-a' }), line({ speaker: 'legacy-key' })])).toBe(false)
  })

  it('castが無い過去回は台本に登場するspeaker keyの種類数で判定する既存動作', () => {
    expect(shouldShowSpeakerSelect(null, [line({ speaker: 'male' })])).toBe(false)
    expect(shouldShowSpeakerSelect(null, [line({ speaker: 'male' }), line({ speaker: 'female' })])).toBe(true)
  })
})

describe('initialSpeakerKey', () => {
  it('castがあれば先頭のkeyを返す', () => {
    const members = cast([{ key: 'mc-a' }, { key: 'mc-b' }])
    expect(initialSpeakerKey(members, [])).toBe('mc-a')
  })

  it('castが無ければ既存動作（登場済みの先頭、無ければmale）', () => {
    expect(initialSpeakerKey(null, [line({ speaker: 'female' })])).toBe('female')
    expect(initialSpeakerKey(null, [])).toBe('male')
  })
})

describe('isSpeakerOutsideCast', () => {
  it('castのどのkeyとも一致しなければtrue', () => {
    const members = cast([{ key: 'mc-a' }])
    expect(isSpeakerOutsideCast(members, 'legacy-key')).toBe(true)
  })

  it('castのkeyと一致すればfalse', () => {
    const members = cast([{ key: 'mc-a' }])
    expect(isSpeakerOutsideCast(members, 'mc-a')).toBe(false)
  })

  it('castが無い/空の場合は常にfalse（過去回の既存動作に影響しない）', () => {
    expect(isSpeakerOutsideCast(null, 'male')).toBe(false)
    expect(isSpeakerOutsideCast([], 'male')).toBe(false)
  })
})

describe('diffScriptLines', () => {
  it('同一行はsameとして扱う', () => {
    const local = [line({ text: 'A' }), line({ text: 'B' })]
    const server = [line({ text: 'A' }), line({ text: 'B' })]
    const ops = diffScriptLines(local, server)
    expect(ops.map((op) => op.kind)).toEqual(['same', 'same'])
  })

  it('端末のみの変更をlocal-only、サーバーのみの変更をserver-onlyとして扱う', () => {
    const local = [line({ text: 'A' }), line({ text: 'ローカル変更' })]
    const server = [line({ text: 'A' }), line({ text: 'サーバー変更' })]
    const ops = diffScriptLines(local, server)
    expect(ops).toEqual([
      { kind: 'same', line: local[0] },
      { kind: 'local-only', line: local[1] },
      { kind: 'server-only', line: server[1] },
    ])
  })

  it('追加された行を検出する', () => {
    const local = [line({ text: 'A' })]
    const server = [line({ text: 'A' }), line({ text: '追加された行' })]
    const ops = diffScriptLines(local, server)
    expect(ops).toEqual([
      { kind: 'same', line: local[0] },
      { kind: 'server-only', line: server[1] },
    ])
  })
})

describe('draft storage', () => {
  const episodeId = 42

  afterEach(() => {
    clearDraftFromStorage(episodeId)
  })

  it('保存した下書きを読み込める', () => {
    const script = { lines: [line({ text: '下書き' })] }
    saveDraftToStorage(episodeId, 3, script)
    const draft = loadDraftFromStorage(episodeId)
    expect(draft?.baseRevision).toBe(3)
    expect(draft?.script.lines[0].text).toBe('下書き')
  })

  it('下書きが無ければnullを返す', () => {
    expect(loadDraftFromStorage(999)).toBeNull()
  })

  it('破棄すると読み込めなくなる', () => {
    saveDraftToStorage(episodeId, 1, { lines: [] })
    clearDraftFromStorage(episodeId)
    expect(loadDraftFromStorage(episodeId)).toBeNull()
  })

  it('壊れたJSONは無視してnullを返す', () => {
    window.localStorage.setItem('admin-script-review-draft:42', '{not-json')
    expect(loadDraftFromStorage(episodeId)).toBeNull()
  })
})

describe('saveScriptClient', () => {
  const originalFetch = global.fetch

  afterEach(() => {
    global.fetch = originalFetch
  })

  it('409かつlatest_revisionがある場合はScriptRevisionConflictErrorを投げる', async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: false,
      status: 409,
      json: async () => ({ detail: { message: 'Script revision conflict', latest_revision: 5 } }),
    }) as unknown as typeof fetch

    await expect(saveScriptClient(1, 1, { lines: [] })).rejects.toBeInstanceOf(ScriptRevisionConflictError)
  })

  it('409だがステータス起因（文字列detail）の場合は通常のScriptApiError', async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: false,
      status: 409,
      json: async () => ({ detail: 'Episode is not awaiting review' }),
    }) as unknown as typeof fetch

    await expect(saveScriptClient(1, 1, { lines: [] })).rejects.toMatchObject({
      status: 409,
      message: 'Episode is not awaiting review',
    })
  })

  it('成功時は保存結果を返す', async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ episode_id: 1, revision: 2, script: { lines: [] } }),
    }) as unknown as typeof fetch

    const result = await saveScriptClient(1, 1, { lines: [] })
    expect(result.revision).toBe(2)
  })
})

describe('approveScriptClient', () => {
  const originalFetch = global.fetch

  afterEach(() => {
    global.fetch = originalFetch
  })

  it('409かつresultsがある場合はScriptValidationBlockedErrorを投げる', async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: false,
      status: 409,
      json: async () => ({ detail: { message: 'Script has validation errors', results: [{ code: 'X', message: 'NG', line_indices: [], severity: 'error' }] } }),
    }) as unknown as typeof fetch

    await expect(approveScriptClient(1)).rejects.toBeInstanceOf(ScriptValidationBlockedError)
  })
})

describe('previewAudioClient', () => {
  const originalFetch = global.fetch

  afterEach(() => {
    global.fetch = originalFetch
  })

  it('429は利用回数上限メッセージになる', async () => {
    global.fetch = jest.fn().mockResolvedValue({ ok: false, status: 429 }) as unknown as typeof fetch
    await expect(previewAudioClient(1, 0)).rejects.toMatchObject({
      status: 429,
      message: expect.stringContaining('上限'),
    })
  })

  it('502は音声生成失敗メッセージになる', async () => {
    global.fetch = jest.fn().mockResolvedValue({ ok: false, status: 502 }) as unknown as typeof fetch
    await expect(previewAudioClient(1, 0)).rejects.toMatchObject({
      status: 502,
      message: expect.stringContaining('音声の生成に失敗'),
    })
  })

  it('成功時はBlobを返す', async () => {
    const blob = new Blob(['wav'])
    global.fetch = jest.fn().mockResolvedValue({ ok: true, status: 200, blob: async () => blob }) as unknown as typeof fetch
    const result = await previewAudioClient(1, 0)
    expect(result).toBe(blob)
  })
})

describe('ScriptApiError', () => {
  it('messageとstatusを保持する', () => {
    const err = new ScriptApiError(500, 'boom')
    expect(err.status).toBe(500)
    expect(err.message).toBe('boom')
  })
})
