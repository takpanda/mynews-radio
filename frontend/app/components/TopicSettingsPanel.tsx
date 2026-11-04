'use client'

import { useEffect, useRef, useState } from 'react'
import {
  createUserTopic,
  deleteUserTopic,
  fetchUserTopics,
  updateUserTopic,
  type TopicWeight,
  type UserTopic,
  type UserTopicLimits,
} from '../lib/api'

const WEIGHTS: Array<{ value: TopicWeight; label: string }> = [
  { value: 'high', label: '高' },
  { value: 'medium', label: '中' },
  { value: 'low', label: '低' },
]

const DEFAULT_LIMITS: UserTopicLimits = { max_topics: 20, name_max_length: 40, description_max_length: 200 }
const DESCRIPTION_HINT = '関連しそうな言葉を書くと判定が安定します'
const inputClass = 'w-full rounded-md border border-slate-200 bg-white px-2 py-1 text-xs text-slate-800 placeholder:text-slate-400 focus:border-sky-500 focus:outline-none disabled:opacity-50'

function validate(name: string, description: string, limits: UserTopicLimits): string | null {
  const trimmed = name.trim()
  if (trimmed.length < 1) return 'トピック名を入力してください'
  if (trimmed.length > limits.name_max_length) return `トピック名は${limits.name_max_length}文字以内で入力してください`
  if (description.trim().length > limits.description_max_length) return `補足は${limits.description_max_length}文字以内で入力してください`
  return null
}

type TopicPatch = Partial<Pick<UserTopic, 'name' | 'description' | 'weight'>>

interface RowProps {
  topic: UserTopic
  limits: UserTopicLimits
  onSave: (topic: UserTopic, patch: TopicPatch) => Promise<boolean>
  onDelete: (topic: UserTopic) => void
  onInvalid: (message: string) => void
}

function TopicRow({ topic, limits, onSave, onDelete, onInvalid }: RowProps) {
  const [name, setName] = useState(topic.name)
  const [description, setDescription] = useState(topic.description)

  // 保存失敗で一覧が元に戻ったとき、入力欄も元の値へ戻す
  useEffect(() => { setName(topic.name); setDescription(topic.description) }, [topic.name, topic.description])

  const commitText = async () => {
    if (name === topic.name && description === topic.description) return
    const message = validate(name, description, limits)
    if (message) { onInvalid(message); setName(topic.name); setDescription(topic.description); return }
    const ok = await onSave(topic, { name: name.trim(), description: description.trim() })
    if (!ok) { setName(topic.name); setDescription(topic.description) }
  }

  return (
    <li className="rounded-lg border border-slate-200 bg-white p-2">
      <div className="grid gap-1.5 sm:grid-cols-2">
        <input
          type="text"
          value={name}
          maxLength={limits.name_max_length}
          onChange={(e) => setName(e.target.value)}
          onBlur={commitText}
          aria-label={`トピック名: ${topic.name}`}
          className={inputClass}
        />
        <input
          type="text"
          value={description}
          maxLength={limits.description_max_length}
          onChange={(e) => setDescription(e.target.value)}
          onBlur={commitText}
          placeholder="補足（任意）"
          aria-label={`補足: ${topic.name}`}
          className={inputClass}
        />
      </div>
      <div className="mt-1.5 flex items-center justify-between gap-2">
        <div role="radiogroup" aria-label={`比重: ${topic.name}`} className="flex gap-1">
          {WEIGHTS.map((w) => (
            <label
              key={w.value}
              className={`cursor-pointer rounded-full border px-2.5 py-0.5 text-xs transition ${topic.weight === w.value ? 'border-sky-500 bg-sky-50 text-sky-700' : 'border-slate-200 bg-white text-slate-500 hover:border-slate-300'}`}
            >
              <input
                type="radio"
                name={`topic-weight-${topic.id}`}
                value={w.value}
                checked={topic.weight === w.value}
                      onChange={() => { if (topic.weight !== w.value) void onSave(topic, { weight: w.value }) }}
                aria-label={`${topic.name}の比重 ${w.label}`}
                className="sr-only"
              />
              {w.label}
            </label>
          ))}
        </div>
        <button
          type="button"
          onClick={() => onDelete(topic)}
          aria-label={`${topic.name}を削除`}
          className="shrink-0 text-xs text-slate-500 underline decoration-slate-300 underline-offset-2 transition hover:text-rose-700 disabled:cursor-not-allowed disabled:opacity-40"
        >
          削除
        </button>
      </div>
    </li>
  )
}

export default function TopicSettingsPanel({ disabled = false }: { disabled?: boolean }) {
  const [topics, setTopics] = useState<UserTopic[]>([])
  const [limits, setLimits] = useState<UserTopicLimits>(DEFAULT_LIMITS)
  const [loading, setLoading] = useState(true)
  const [pending, setPending] = useState(0)
  const [error, setError] = useState<string | null>(null)
  const [loadFailed, setLoadFailed] = useState(false)
  const [saved, setSaved] = useState(false)
  const [newName, setNewName] = useState('')
  const [newDescription, setNewDescription] = useState('')
  const [newWeight, setNewWeight] = useState<TopicWeight>('medium')
  const queueRef = useRef<Promise<unknown>>(Promise.resolve())
  const topicsRef = useRef<UserTopic[]>([])
  const addingRef = useRef(false)
  const busy = pending > 0
  const authRequired = error?.includes('ログインが必要') ?? false

  const applyTopics = (updater: (current: UserTopic[]) => UserTopic[]) => {
    topicsRef.current = updater(topicsRef.current)
    setTopics(topicsRef.current)
  }

  const load = () => {
    setLoading(true); setLoadFailed(false); setError(null)
    fetchUserTopics()
      .then((value) => { topicsRef.current = value.topics; setTopics(value.topics); setLimits(value.limits ?? DEFAULT_LIMITS) })
      .catch((err) => { setLoadFailed(true); setError(err instanceof Error ? err.message : '関心トピックの読み込みに失敗しました') })
      .finally(() => setLoading(false))
  }

  useEffect(load, [])

  // 保存はキューで順番に実行する。保存中も入力・クリックを受け付け、フォーカスを奪わない。
  // 失敗時は呼び出し側が元の状態へ戻せるよう false を返す
  const run = (action: () => Promise<void>, fallback: string): Promise<boolean> => {
    setPending((n) => n + 1)
    const task = queueRef.current.then(async () => {
      setSaved(false); setError(null)
      try { await action(); setSaved(true); return true }
      catch (err) { setError(err instanceof Error ? err.message : fallback); return false }
      finally { setPending((n) => n - 1) }
    })
    queueRef.current = task
    return task
  }

  const save = (topic: UserTopic, patch: TopicPatch) =>
    run(async () => {
      // 先行する保存の結果を反映した最新値に変更分だけを重ねる（is_active も維持する）
      const latest = topicsRef.current.find((item) => item.id === topic.id)
      if (!latest) return
      const updated = await updateUserTopic(topic.id, {
        name: latest.name,
        description: latest.description,
        weight: latest.weight,
        is_active: latest.is_active,
        ...patch,
      })
      applyTopics((current) => current.map((item) => (item.id === updated.id ? updated : item)))
    }, '関心トピックを更新できませんでした')

  const remove = (topic: UserTopic) => {
    void run(async () => {
      await deleteUserTopic(topic.id)
      applyTopics((current) => current.filter((item) => item.id !== topic.id))
    }, '関心トピックを削除できませんでした')
  }

  const reachedLimit = topics.length >= limits.max_topics
  const addDisabled = reachedLimit || loadFailed
  const addError = newName === '' && newDescription === '' ? null : validate(newName, newDescription, limits)

  const add = async (event: React.FormEvent) => {
    event.preventDefault()
    const message = validate(newName, newDescription, limits)
    if (message) { setError(message); return }
    if (addingRef.current) return
    addingRef.current = true
    const ok = await run(async () => {
      const created = await createUserTopic({ name: newName.trim(), description: newDescription.trim(), weight: newWeight })
      applyTopics((current) => [...current, created])
    }, '関心トピックを追加できませんでした')
    addingRef.current = false
    if (ok) { setNewName(''); setNewDescription(''); setNewWeight('medium') }
  }

  const locked = disabled || loading || authRequired

  return (
    <fieldset className="rounded-xl border border-slate-200 bg-slate-50/70 p-3" disabled={locked}>
      <legend className="px-1 text-sm font-medium text-slate-900">関心トピック</legend>
      <p className="mt-1 text-xs leading-5 text-slate-500">
        登録したトピックに合う記事を優先して選びます。比重が高いほど優先されます（最大{limits.max_topics}件）。
      </p>

      {!loading && topics.length === 0 && !authRequired && (
        <p className="mt-3 text-xs text-slate-400">まだトピックがありません。下のフォームから追加できます。</p>
      )}
      {topics.length > 0 && (
        <ul className="mt-3 space-y-2" aria-label="関心トピック一覧">
          {topics.map((topic) => (
            <TopicRow
              key={topic.id}
              topic={topic}
              limits={limits}
              onSave={save}
              onDelete={remove}
              onInvalid={setError}
            />
          ))}
        </ul>
      )}

      <form onSubmit={add} className="mt-3 rounded-lg border border-dashed border-slate-300 bg-white p-2" aria-label="関心トピックの追加">
        <div className="grid gap-1.5 sm:grid-cols-2">
          <input
            type="text"
            value={newName}
            maxLength={limits.name_max_length}
            onChange={(e) => setNewName(e.target.value)}
            disabled={addDisabled}
            placeholder="トピック名（例: ローカルLLM）"
            aria-label="新しいトピック名"
            className={inputClass}
          />
          <input
            type="text"
            value={newDescription}
            maxLength={limits.description_max_length}
            onChange={(e) => setNewDescription(e.target.value)}
            disabled={addDisabled}
            placeholder="補足（任意）"
            aria-label="新しいトピックの補足"
            aria-describedby="topic-description-hint"
            className={inputClass}
          />
        </div>
        <p id="topic-description-hint" className="mt-1 text-[10px] text-slate-400">補足: {DESCRIPTION_HINT}</p>
        <div className="mt-1.5 flex items-center justify-between gap-2">
          <div role="radiogroup" aria-label="新しいトピックの比重" className="flex gap-1">
            {WEIGHTS.map((w) => (
              <label
                key={w.value}
                className={`cursor-pointer rounded-full border px-2.5 py-0.5 text-xs transition ${newWeight === w.value ? 'border-sky-500 bg-sky-50 text-sky-700' : 'border-slate-200 bg-white text-slate-500 hover:border-slate-300'}`}
              >
                <input
                  type="radio"
                  name="new-topic-weight"
                  value={w.value}
                  checked={newWeight === w.value}
                  disabled={addDisabled}
                  onChange={() => setNewWeight(w.value)}
                  aria-label={`新しいトピックの比重 ${w.label}`}
                  className="sr-only"
                />
                {w.label}
              </label>
            ))}
          </div>
          <button
            type="submit"
            disabled={addDisabled || newName.trim() === '' || addError !== null}
            className="shrink-0 rounded-md border border-sky-500 bg-sky-50 px-3 py-1 text-xs text-sky-700 transition hover:bg-sky-100 disabled:cursor-not-allowed disabled:opacity-40"
          >
            追加
          </button>
        </div>
        {reachedLimit && !loadFailed && <p className="mt-1 text-xs text-slate-500">登録数が上限（{limits.max_topics}件）に達しています。追加するには既存のトピックを削除してください。</p>}
        {!addDisabled && addError && <p className="mt-1 text-xs text-rose-600">{addError}</p>}
      </form>

      <div className="mt-2 flex min-h-5 items-center text-xs" aria-live="polite">
        <span className={error ? 'text-rose-600' : 'text-slate-400'}>
          {loading ? '読み込み中…' : error ? (
            <>
              {error}
              {authRequired && <a href="/admin/login" className="ml-2 underline hover:text-rose-800">ログインする</a>}
              {loadFailed && !authRequired && <button type="button" onClick={load} className="ml-2 rounded-md border border-rose-200 bg-white px-2 py-0.5 text-rose-700 transition hover:bg-rose-50">再読み込み</button>}
            </>
          ) : busy ? '保存中…' : saved ? '保存しました' : ''}
        </span>
      </div>
    </fieldset>
  )
}
