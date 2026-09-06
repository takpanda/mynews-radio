'use client'

import { useState } from 'react'
import FemaleMcCandidatesPanel from './FemaleMcCandidatesPanel'
import { fetchFemaleMcCandidatesClient, type FemaleMcCandidate } from '../lib/admin-female-mc-candidates'

interface Props {
  initialData: FemaleMcCandidate[] | null
  initialError: string | null
}

export default function FemaleMcCandidatesSection({ initialData, initialError }: Props) {
  const [data, setData] = useState<FemaleMcCandidate[] | null>(initialData)
  const [error, setError] = useState<string | null>(initialError)
  const [retrying, setRetrying] = useState(false)

  const handleRetry = async () => {
    if (retrying) return
    setRetrying(true)
    try {
      const fresh = await fetchFemaleMcCandidatesClient()
      setData(fresh)
      setError(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : '女性MC候補マスタを取得できませんでした。しばらく後でもう一度お試しください。')
    } finally {
      setRetrying(false)
    }
  }

  if (data) {
    return <FemaleMcCandidatesPanel initialData={data} />
  }

  return (
    <div className="rounded-2xl border border-red-200 bg-red-50 p-4">
      <p role="alert" className="text-sm text-red-700">
        {error}
      </p>
      <button
        type="button"
        onClick={handleRetry}
        disabled={retrying}
        aria-label={retrying ? '女性MC候補マスタを再試行中' : '女性MC候補マスタを再試行'}
        className="mt-3 rounded-md border border-red-300 bg-white px-3 py-1.5 text-xs font-medium text-red-700 transition hover:bg-red-100 disabled:cursor-not-allowed disabled:opacity-50"
      >
        {retrying ? '再試行中…' : '再試行'}
      </button>
    </div>
  )
}
