import Link from 'next/link'
import type { EpisodeListItem } from '../lib/api'
import { formatDate } from '../lib/api'
import SynthesizeAudioButton from './SynthesizeAudioButton'

interface Props {
  episodes: EpisodeListItem[]
}

function formatDuration(seconds: number): string {
  if (!seconds || seconds <= 0) return ''
  const m = Math.floor(seconds / 60)
  return m > 0 ? `${m}分` : ''
}

export default function EpisodeList({ episodes }: Props) {
  if (episodes.length === 0) {
    return (
      <div className="text-center py-12">
        <p className="text-4xl mb-3">📻</p>
        <p className="text-gray-500">番組がまだありません</p>
      </div>
    )
  }

  return (
    <div className="space-y-3">
      {episodes.map((ep) => (
        <div key={ep.id} className="bg-white rounded-xl shadow-sm overflow-hidden hover:shadow-md transition-shadow">
          <Link
            href={`/episodes/${ep.id}`}
            className="block p-4 active:bg-gray-50"
          >
            <div className="flex items-start justify-between gap-2">
              <div className="min-w-0">
                <p className="font-medium text-gray-900 truncate">
                  {ep.title || `エピソード #${ep.id}`}
                </p>
                {ep.subtitle && (
                  <p className="text-xs text-blue-500 mt-0.5 truncate">{ep.subtitle}</p>
                )}
                <p className="text-sm text-gray-500 mt-1">{formatDate(ep.date)}</p>
              </div>
              {ep.duration > 0 && (
                <span className="text-xs text-gray-400 flex-shrink-0 mt-1">
                  {formatDuration(ep.duration)}
                </span>
              )}
            </div>
          </Link>
          {ep.has_script && !ep.audio_url && (
            <div className="px-4 pb-3 border-t border-slate-100 pt-2.5">
              <SynthesizeAudioButton episodeId={ep.id} compact />
            </div>
          )}
        </div>
      ))}
    </div>
  )
}
