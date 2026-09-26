'use client'

import { useState } from 'react'
import { useRouter } from 'next/navigation'
import toast from 'react-hot-toast'
import {
  createProgram,
  replaceProgram,
  MAX_SEGMENTS,
  SEGMENT_KINDS_BY_PROGRAM_KIND,
  SEGMENT_KIND_LABELS,
  type Mc,
  type Program,
  type ProgramCastValue,
  type ProgramDefinitionValue,
  type ProgramKind,
  type ProgramOptionsValue,
  type ProgramSegmentValue,
  type ReviewMode,
} from '../lib/admin-programs'
import ConfirmDialog from './ConfirmDialog'

interface Props {
  mode: 'create' | 'edit'
  initialProgram: ProgramDefinitionValue
  initialIsActive: boolean
  mcs: Mc[]
}

const KIND_LABEL: Record<ProgramKind, string> = { radio: 'ラジオ', commentary: '解説' }
const REVIEW_MODE_LABEL: Record<ReviewMode, string> = {
  always: '毎回確認',
  on_failure: '検証エラー時のみ確認',
  auto: '自動判定（確認なし）',
}

function emptyCast(): ProgramCastValue {
  return {
    key: '',
    name: '',
    role: '',
    mc_id: null,
    voice_fishs2pro: null,
    voice_aivispeech: null,
    voice_voicevox: null,
  }
}

function emptySegment(order: number, kind: string): ProgramSegmentValue {
  return { id: '', kind, order, min_lines: 0, max_lines: 0, speaker_keys: [], label: '' }
}

function renumber(segments: ProgramSegmentValue[]): ProgramSegmentValue[] {
  return segments.map((segment, index) => ({ ...segment, order: index }))
}

function validate(program: ProgramDefinitionValue): string | null {
  if (!program.id.trim()) return 'IDを入力してください'
  if (!program.name.trim()) return '名前を入力してください'
  if (program.cast.length === 0) return 'キャストを1人以上追加してください'
  const keys = program.cast.map((member) => member.key.trim())
  if (keys.some((key) => !key)) return 'キャストのキーは必須です'
  if (new Set(keys).size !== keys.length) return 'キャストのキーが重複しています'
  if (program.segments.length > MAX_SEGMENTS) return `セグメントは最大${MAX_SEGMENTS}件までです`
  const segmentIds = program.segments.map((segment) => segment.id.trim())
  if (segmentIds.some((id) => !id)) return 'セグメントのIDは必須です'
  if (new Set(segmentIds).size !== segmentIds.length) return 'セグメントのIDが重複しています'
  for (const segment of program.segments) {
    if (segment.min_lines < 0 || segment.max_lines < segment.min_lines) {
      return `セグメント「${segment.id || segment.label}」の行数範囲が不正です`
    }
  }
  return null
}

export default function AdminProgramFormShell({ mode, initialProgram, initialIsActive, mcs }: Props) {
  const router = useRouter()
  const isEdit = mode === 'edit'

  const [id, setId] = useState(initialProgram.id)
  const [name, setName] = useState(initialProgram.name)
  const [kind, setKind] = useState<ProgramKind>(initialProgram.kind)
  const [isActive, setIsActive] = useState(initialIsActive)
  const [cast, setCast] = useState<ProgramCastValue[]>(initialProgram.cast)
  const [segments, setSegments] = useState<ProgramSegmentValue[]>(initialProgram.segments)
  const [options, setOptions] = useState<ProgramOptionsValue>(initialProgram.options)

  const [formError, setFormError] = useState<string | null>(null)
  const [segmentLimitError, setSegmentLimitError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [noteDialog, setNoteDialog] = useState<{ note: string; error: string | null } | null>(null)

  const allowedSegmentKinds = SEGMENT_KINDS_BY_PROGRAM_KIND[kind]
  const castKeys = cast.map((member) => member.key).filter(Boolean)

  const updateCast = (index: number, patch: Partial<ProgramCastValue>) => {
    setCast((prev) => prev.map((member, i) => (i === index ? { ...member, ...patch } : member)))
  }
  const addCast = () => setCast((prev) => [...prev, emptyCast()])
  const removeCast = (index: number) => setCast((prev) => prev.filter((_, i) => i !== index))

  const updateSegment = (index: number, patch: Partial<ProgramSegmentValue>) => {
    setSegments((prev) => prev.map((segment, i) => (i === index ? { ...segment, ...patch } : segment)))
  }
  const addSegment = () => {
    if (segments.length >= MAX_SEGMENTS) {
      setSegmentLimitError(`セグメントは最大${MAX_SEGMENTS}件までです`)
      return
    }
    setSegmentLimitError(null)
    setSegments((prev) => [...prev, emptySegment(prev.length, allowedSegmentKinds[0])])
  }
  const removeSegment = (index: number) => {
    setSegmentLimitError(null)
    setSegments((prev) => renumber(prev.filter((_, i) => i !== index)))
  }
  const moveSegment = (index: number, direction: -1 | 1) => {
    const target = index + direction
    if (target < 0 || target >= segments.length) return
    setSegments((prev) => {
      const next = [...prev]
      ;[next[index], next[target]] = [next[target], next[index]]
      return renumber(next)
    })
  }
  const toggleSpeakerKey = (index: number, key: string) => {
    setSegments((prev) =>
      prev.map((segment, i) => {
        if (i !== index) return segment
        const has = segment.speaker_keys.includes(key)
        return {
          ...segment,
          speaker_keys: has ? segment.speaker_keys.filter((k) => k !== key) : [...segment.speaker_keys, key],
        }
      }),
    )
  }

  const handleKindChange = (nextKind: ProgramKind) => {
    setKind(nextKind)
    // commentaryはnarrative_arcを受け付けない（validate_program_profile）。
    // チェックボックスはradioのときしか表示できないため、切り替え時に自動で落とす。
    if (nextKind === 'commentary') {
      setOptions((prev) => (prev.narrative_arc ? { ...prev, narrative_arc: false } : prev))
    }
    // 新しい種別で使えないセグメント種類（例: radioのtransition/discussion）が
    // 残ると保存時に422になるため、許可された種類へ置き換える。
    const allowed = SEGMENT_KINDS_BY_PROGRAM_KIND[nextKind]
    setSegments((prev) =>
      prev.map((segment) => (allowed.includes(segment.kind) ? segment : { ...segment, kind: allowed[0] })),
    )
  }

  const buildPayload = (): ProgramDefinitionValue => ({
    id: id.trim(),
    name: name.trim(),
    kind,
    cast: cast.map((member) => ({ ...member, key: member.key.trim() })),
    segments: renumber(segments).map((segment) => ({
      ...segment,
      id: segment.id.trim(),
      speaker_keys: segment.speaker_keys.filter((key) => castKeys.includes(key)),
    })),
    options,
  })

  const handleSaveClick = () => {
    const payload = buildPayload()
    const error = validate(payload)
    if (error) {
      setFormError(error)
      return
    }
    setFormError(null)
    if (isEdit) {
      setNoteDialog({ note: '', error: null })
    } else {
      void doCreate(payload)
    }
  }

  const doCreate = async (payload: ProgramDefinitionValue) => {
    setSubmitting(true)
    try {
      const created = await createProgram({ ...payload, is_active: isActive })
      toast.success('番組を作成しました')
      router.push(`/admin/programs/${encodeURIComponent(created.id)}`)
    } catch (err) {
      setFormError(err instanceof Error ? err.message : '保存に失敗しました')
    } finally {
      setSubmitting(false)
    }
  }

  const handleNoteConfirm = async () => {
    if (!noteDialog) return
    if (!noteDialog.note.trim()) {
      setNoteDialog({ ...noteDialog, error: '変更メモを入力してください' })
      return
    }
    const payload = buildPayload()
    setSubmitting(true)
    try {
      const updated: Program = await replaceProgram(initialProgram.id, { ...payload, is_active: isActive })
      toast.success('番組を保存しました。変更はすぐに反映されます。')
      setNoteDialog(null)
      setId(updated.id)
      setName(updated.name)
      setKind(updated.kind)
      setIsActive(updated.is_active)
      setCast(updated.definition.cast)
      setSegments(updated.definition.segments)
      setOptions(updated.definition.options)
      router.refresh()
    } catch (err) {
      setNoteDialog({ ...noteDialog, error: err instanceof Error ? err.message : '保存に失敗しました' })
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="space-y-5">
      {/* モバイル: 閲覧専用サマリー */}
      <div className="space-y-5 md:hidden" data-testid="program-mobile-summary">
        <ReadOnlySummary
          id={id}
          name={name}
          kind={kind}
          isActive={isActive}
          cast={cast}
          segments={segments}
          options={options}
        />
      </div>

      {/* PC: 編集フォーム */}
      <div className="hidden space-y-5 md:block" data-testid="program-edit-form">
        <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm sm:p-6">
          <h1 className="text-lg font-semibold text-slate-900">{isEdit ? '番組を編集' : '番組を新規作成'}</h1>
          {isEdit && (
            <p className="mt-1 text-sm text-slate-500">保存すると本番の番組定義がすぐに反映されます。</p>
          )}

          <div className="mt-4 grid gap-3 sm:grid-cols-2">
            <div>
              <label className="mb-1 block text-xs font-medium text-slate-500">
                ID <span className="text-red-500">*</span>
              </label>
              <input
                type="text"
                value={id}
                onChange={(e) => setId(e.target.value)}
                disabled={isEdit}
                maxLength={100}
                className="w-full rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-900 transition focus:border-sky-400 focus:bg-white focus:outline-none focus:ring-2 focus:ring-sky-100 disabled:bg-slate-100 disabled:text-slate-500"
              />
            </div>
            <div>
              <label className="mb-1 block text-xs font-medium text-slate-500">
                名前 <span className="text-red-500">*</span>
              </label>
              <input
                type="text"
                value={name}
                onChange={(e) => setName(e.target.value)}
                maxLength={200}
                className="w-full rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-900 transition focus:border-sky-400 focus:bg-white focus:outline-none focus:ring-2 focus:ring-sky-100"
              />
            </div>
            <div>
              <label className="mb-1 block text-xs font-medium text-slate-500">種別</label>
              <select
                value={kind}
                onChange={(e) => handleKindChange(e.target.value as ProgramKind)}
                className="w-full rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-700 transition focus:border-sky-400 focus:bg-white focus:outline-none focus:ring-2 focus:ring-sky-100"
              >
                {(['radio', 'commentary'] as ProgramKind[]).map((k) => (
                  <option key={k} value={k}>
                    {KIND_LABEL[k]}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="mb-1 block text-xs font-medium text-slate-500">状態</label>
              <div className="flex h-9 items-center gap-3">
                <button
                  type="button"
                  onClick={() => setIsActive((prev) => !prev)}
                  className="relative inline-flex h-6 w-11 shrink-0 cursor-pointer items-center rounded-full transition"
                  role="switch"
                  aria-checked={isActive}
                >
                  <span className={`inline-block h-6 w-11 rounded-full transition-colors ${isActive ? 'bg-emerald-500' : 'bg-slate-300'}`} />
                  <span
                    className={`absolute left-0.5 inline-block h-5 w-5 transform rounded-full bg-white shadow-sm transition-transform ${
                      isActive ? 'translate-x-5' : 'translate-x-0.5'
                    }`}
                  />
                </button>
                <span className={`text-xs font-medium ${isActive ? 'text-emerald-700' : 'text-slate-400'}`}>
                  {isActive ? '有効' : '無効'}
                </span>
              </div>
            </div>
          </div>
        </div>

        {/* キャスト */}
        <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm sm:p-6">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-semibold text-slate-900">キャスト</h2>
            <button
              type="button"
              onClick={addCast}
              className="rounded-full bg-slate-100 px-3 py-1.5 text-xs font-medium text-slate-700 transition hover:bg-slate-200"
            >
              キャストを追加
            </button>
          </div>
          <div className="mt-3 space-y-3">
            {cast.length === 0 && <p className="text-sm text-slate-400">キャストがまだありません。</p>}
            {cast.map((member, index) => (
              <div key={index} className="rounded-xl border border-slate-100 bg-slate-50 p-3">
                <div className="grid gap-2 sm:grid-cols-6">
                  <LabeledInput label="キー" value={member.key} onChange={(v) => updateCast(index, { key: v })} />
                  <LabeledInput label="名前" value={member.name} onChange={(v) => updateCast(index, { name: v })} />
                  <LabeledInput label="役割" value={member.role} onChange={(v) => updateCast(index, { role: v })} />
                  <div>
                    <label className="mb-1 block text-xs font-medium text-slate-500">MC</label>
                    <select
                      value={member.mc_id ?? ''}
                      onChange={(e) => updateCast(index, { mc_id: e.target.value || null })}
                      className="w-full rounded-lg border border-slate-200 bg-white px-2 py-1.5 text-sm"
                    >
                      <option value="">未設定</option>
                      {mcs.map((mc) => (
                        <option key={mc.id} value={mc.id}>
                          {(mc.name || mc.id) + (mc.is_active ? '' : '（無効）')}
                        </option>
                      ))}
                    </select>
                  </div>
                  <LabeledInput
                    label="Fish S2 Pro"
                    value={member.voice_fishs2pro ?? ''}
                    onChange={(v) => updateCast(index, { voice_fishs2pro: v || null })}
                  />
                  <div className="flex items-end">
                    <button
                      type="button"
                      onClick={() => removeCast(index)}
                      className="w-full rounded-lg border border-red-200 px-2 py-1.5 text-xs text-red-600 transition hover:bg-red-50"
                    >
                      削除
                    </button>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* セグメント */}
        <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm sm:p-6">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-semibold text-slate-900">
              セグメント（{segments.length}/{MAX_SEGMENTS}）
            </h2>
            <button
              type="button"
              onClick={addSegment}
              className="rounded-full bg-slate-100 px-3 py-1.5 text-xs font-medium text-slate-700 transition hover:bg-slate-200"
            >
              セグメントを追加
            </button>
          </div>
          {segmentLimitError && <p className="mt-2 text-xs text-red-600">{segmentLimitError}</p>}
          <div className="mt-3 space-y-3">
            {segments.length === 0 && <p className="text-sm text-slate-400">セグメントがまだありません。</p>}
            {segments.map((segment, index) => (
              <div key={index} className="rounded-xl border border-slate-100 bg-slate-50 p-3">
                <div className="grid gap-2 sm:grid-cols-6">
                  <LabeledInput label="ID" value={segment.id} onChange={(v) => updateSegment(index, { id: v })} />
                  <div>
                    <label className="mb-1 block text-xs font-medium text-slate-500">種類</label>
                    <select
                      value={segment.kind}
                      onChange={(e) => updateSegment(index, { kind: e.target.value })}
                      className="w-full rounded-lg border border-slate-200 bg-white px-2 py-1.5 text-sm"
                    >
                      {allowedSegmentKinds.map((k) => (
                        <option key={k} value={k}>
                          {SEGMENT_KIND_LABELS[k] ?? k}
                        </option>
                      ))}
                    </select>
                  </div>
                  <LabeledNumberInput
                    label="最小行数"
                    value={segment.min_lines}
                    onChange={(v) => updateSegment(index, { min_lines: v })}
                  />
                  <LabeledNumberInput
                    label="最大行数"
                    value={segment.max_lines}
                    onChange={(v) => updateSegment(index, { max_lines: v })}
                  />
                  <LabeledInput label="表示ラベル" value={segment.label} onChange={(v) => updateSegment(index, { label: v })} />
                  <div className="flex items-end gap-1">
                    <button
                      type="button"
                      onClick={() => moveSegment(index, -1)}
                      disabled={index === 0}
                      aria-label={`${segment.id || index + 1}番目のセグメントを上へ`}
                      className="rounded-lg border border-slate-200 px-2 py-1.5 text-xs text-slate-600 transition hover:bg-slate-100 disabled:cursor-not-allowed disabled:opacity-40"
                    >
                      ▲
                    </button>
                    <button
                      type="button"
                      onClick={() => moveSegment(index, 1)}
                      disabled={index === segments.length - 1}
                      aria-label={`${segment.id || index + 1}番目のセグメントを下へ`}
                      className="rounded-lg border border-slate-200 px-2 py-1.5 text-xs text-slate-600 transition hover:bg-slate-100 disabled:cursor-not-allowed disabled:opacity-40"
                    >
                      ▼
                    </button>
                    <button
                      type="button"
                      onClick={() => removeSegment(index)}
                      className="rounded-lg border border-red-200 px-2 py-1.5 text-xs text-red-600 transition hover:bg-red-50"
                    >
                      削除
                    </button>
                  </div>
                </div>
                <div className="mt-2">
                  <span className="mb-1 block text-xs font-medium text-slate-500">話者</span>
                  <div className="flex flex-wrap gap-3">
                    {castKeys.length === 0 && <span className="text-xs text-slate-400">キャストを先に追加してください</span>}
                    {castKeys.map((key) => (
                      <label key={key} className="inline-flex items-center gap-1.5 text-xs text-slate-600">
                        <input
                          type="checkbox"
                          checked={segment.speaker_keys.includes(key)}
                          onChange={() => toggleSpeakerKey(index, key)}
                          className="h-3.5 w-3.5 rounded border-slate-300 text-sky-600 focus:ring-sky-300"
                        />
                        {key}
                      </label>
                    ))}
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* オプション */}
        <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm sm:p-6">
          <h2 className="text-sm font-semibold text-slate-900">オプション</h2>
          <div className="mt-3 grid gap-3 sm:grid-cols-2">
            <div>
              <label className="mb-1 block text-xs font-medium text-slate-500">台本確認モード</label>
              <select
                value={options.review_mode}
                onChange={(e) => setOptions((prev) => ({ ...prev, review_mode: e.target.value as ReviewMode }))}
                className="w-full rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-sm"
              >
                {(['always', 'on_failure', 'auto'] as ReviewMode[]).map((m) => (
                  <option key={m} value={m}>
                    {REVIEW_MODE_LABEL[m]}
                  </option>
                ))}
              </select>
            </div>
            {kind === 'radio' && (
              <label className="flex items-end gap-2 pb-2 text-sm text-slate-600">
                <input
                  type="checkbox"
                  checked={options.narrative_arc}
                  onChange={(e) => setOptions((prev) => ({ ...prev, narrative_arc: e.target.checked }))}
                  className="h-4 w-4 rounded border-slate-300 text-sky-600 focus:ring-sky-300"
                />
                物語構成（narrative_arc）を使う
              </label>
            )}
            {kind === 'commentary' && (
              <>
                <div>
                  <label className="mb-1 block text-xs font-medium text-slate-500">スタイル</label>
                  <select
                    value={options.style ?? ''}
                    onChange={(e) => setOptions((prev) => ({ ...prev, style: e.target.value || null }))}
                    className="w-full rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-sm"
                  >
                    <option value="">未設定</option>
                    <option value="solo">ソロ</option>
                    <option value="dialogue">対話</option>
                  </select>
                </div>
                <div>
                  <label className="mb-1 block text-xs font-medium text-slate-500">MC性別キー</label>
                  <select
                    value={options.mc_gender ?? ''}
                    onChange={(e) => setOptions((prev) => ({ ...prev, mc_gender: e.target.value || null }))}
                    className="w-full rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-sm"
                  >
                    <option value="">未設定</option>
                    {castKeys.map((key) => (
                      <option key={key} value={key}>
                        {key}
                      </option>
                    ))}
                  </select>
                </div>
              </>
            )}
          </div>
        </div>

        {formError && (
          <div className="rounded-2xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">{formError}</div>
        )}

        <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm sm:p-6">
          <button
            type="button"
            onClick={handleSaveClick}
            disabled={submitting}
            className="inline-flex items-center gap-1.5 rounded-full bg-sky-600 px-5 py-2 text-sm font-medium text-white transition hover:bg-sky-700 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {submitting && <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-white/30 border-t-white" />}
            {isEdit ? '保存する' : '作成する'}
          </button>
        </div>
      </div>

      {noteDialog && (
        <ConfirmDialog
          title="変更内容を保存"
          message="保存すると番組定義がすぐに本番へ反映されます。変更メモを入力してください。"
          confirmLabel="保存する"
          confirming={submitting}
          error={noteDialog.error}
          onConfirm={handleNoteConfirm}
          onCancel={() => setNoteDialog(null)}
        >
          <textarea
            value={noteDialog.note}
            onChange={(e) => setNoteDialog({ note: e.target.value, error: null })}
            rows={3}
            placeholder="変更メモ（必須）"
            aria-label="変更メモ"
            className="w-full resize-none rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-900 transition focus:border-sky-400 focus:bg-white focus:outline-none focus:ring-2 focus:ring-sky-100"
          />
        </ConfirmDialog>
      )}
    </div>
  )
}

function LabeledInput({ label, value, onChange }: { label: string; value: string; onChange: (v: string) => void }) {
  return (
    <div>
      <label className="mb-1 block text-xs font-medium text-slate-500">{label}</label>
      <input
        type="text"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="w-full rounded-lg border border-slate-200 bg-white px-2 py-1.5 text-sm"
      />
    </div>
  )
}

function LabeledNumberInput({
  label,
  value,
  onChange,
}: {
  label: string
  value: number
  onChange: (v: number) => void
}) {
  return (
    <div>
      <label className="mb-1 block text-xs font-medium text-slate-500">{label}</label>
      <input
        type="number"
        min={0}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className="w-full rounded-lg border border-slate-200 bg-white px-2 py-1.5 text-sm"
      />
    </div>
  )
}

function ReadOnlySummary({
  id,
  name,
  kind,
  isActive,
  cast,
  segments,
  options,
}: {
  id: string
  name: string
  kind: ProgramKind
  isActive: boolean
  cast: ProgramCastValue[]
  segments: ProgramSegmentValue[]
  options: ProgramOptionsValue
}) {
  return (
    <>
      <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
        <p className="text-xs text-slate-400">{id}</p>
        <h1 className="text-lg font-semibold text-slate-900">{name || '(名前未設定)'}</h1>
        <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-slate-500">
          <span className="rounded-full bg-slate-100 px-2 py-0.5">{KIND_LABEL[kind]}</span>
          <span className={`inline-flex items-center gap-1.5 font-medium ${isActive ? 'text-emerald-700' : 'text-slate-400'}`}>
            <span className={`h-2 w-2 rounded-full ${isActive ? 'bg-emerald-500' : 'bg-slate-300'}`} />
            {isActive ? '有効' : '無効'}
          </span>
        </div>
        <p className="mt-3 text-xs text-slate-400">
          スマホ表示では閲覧のみできます。編集・保存はPCから行ってください。
        </p>
      </div>

      <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
        <h2 className="text-sm font-semibold text-slate-900">キャスト</h2>
        <ul className="mt-2 space-y-1 text-sm text-slate-600">
          {cast.length === 0 && <li className="text-slate-400">キャストがありません</li>}
          {cast.map((member, i) => (
            <li key={i}>
              {member.key}: {member.name || '(名前未設定)'} / {member.role || '—'}
              {member.mc_id ? `（MC: ${member.mc_id}）` : ''}
            </li>
          ))}
        </ul>
      </div>

      <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
        <h2 className="text-sm font-semibold text-slate-900">セグメント（{segments.length}件）</h2>
        <ol className="mt-2 space-y-1 text-sm text-slate-600">
          {segments.length === 0 && <li className="text-slate-400">セグメントがありません</li>}
          {segments.map((segment, i) => (
            <li key={i}>
              {segment.order + 1}. {segment.label || SEGMENT_KIND_LABELS[segment.kind] || segment.kind}（{segment.min_lines}〜
              {segment.max_lines}行）
            </li>
          ))}
        </ol>
      </div>

      <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
        <h2 className="text-sm font-semibold text-slate-900">オプション</h2>
        <p className="mt-2 text-sm text-slate-600">台本確認モード: {REVIEW_MODE_LABEL[options.review_mode]}</p>
      </div>
    </>
  )
}
