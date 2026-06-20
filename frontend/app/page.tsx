import {
  fetchLatestEpisode,
  fetchEpisodes,
  buildAudioUrl,
  formatDate,
  type Episode,
  type EpisodeListItem,
} from './lib/api'
import AudioPlayer from './components/AudioPlayer'
import EpisodeList from './components/EpisodeList'
import GenerateEpisodeButton from './components/GenerateEpisodeButton'

export default async function Home() {
  let latestEpisode: Episode | null = null
  let episodes: EpisodeListItem[] = []
  let error: string | null = null

  try {
    ;[latestEpisode, episodes] = await Promise.all([fetchLatestEpisode(), fetchEpisodes()])
  } catch {
    error = 'エラーが発生しました。しばらく後でもう一度お試しください。'
  }

  return (
    <main className="mx-auto max-w-6xl px-4 py-6 sm:px-6 lg:px-8 lg:py-10 overflow-x-hidden">
      <section className="relative overflow-hidden rounded-[2rem] border border-white/70 bg-[radial-gradient(circle_at_top_left,_rgba(254,240,138,0.8),_transparent_30%),linear-gradient(135deg,_rgba(255,255,255,0.96),_rgba(238,244,255,0.92))] px-5 py-6 shadow-[0_24px_80px_rgba(15,23,42,0.12)] sm:px-8 sm:py-8">
        <div className="absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-amber-200 to-transparent" />
        <div className="relative grid gap-6 lg:grid-cols-[minmax(0,1.1fr)_minmax(320px,0.9fr)] lg:items-start">
          <div>
            <p className="inline-flex items-center rounded-full border border-slate-200 bg-white/80 px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.24em] text-slate-600 backdrop-blur">
              Personal News Studio
            </p>
            <h1 className="mt-4 max-w-xl text-4xl font-semibold leading-tight text-slate-950 sm:text-5xl">
              MyNews Radio
            </h1>
            <p className="mt-3 max-w-2xl text-sm leading-7 text-slate-600 sm:text-base">
              気になるニュースを選ぶだけで、通勤や家事の合間に聴けるラジオ番組へ整えます。
              生成設定、進行状況、最新エピソードをひとつの画面で追えるように再構成しました。
            </p>

            <div className="mt-6 grid gap-3 sm:grid-cols-3">
              <div className="rounded-2xl border border-white/80 bg-white/70 p-4 backdrop-blur">
                <p className="text-[11px] font-semibold uppercase tracking-[0.2em] text-slate-500">
                  入力
                </p>
                <p className="mt-2 text-sm font-medium text-slate-900">ニュースソースと音声エンジンを選択</p>
              </div>
              <div className="rounded-2xl border border-white/80 bg-white/70 p-4 backdrop-blur">
                <p className="text-[11px] font-semibold uppercase tracking-[0.2em] text-slate-500">
                  進行
                </p>
                <p className="mt-2 text-sm font-medium text-slate-900">取得から音声生成まで段階表示</p>
              </div>
              <div className="rounded-2xl border border-white/80 bg-white/70 p-4 backdrop-blur">
                <p className="text-[11px] font-semibold uppercase tracking-[0.2em] text-slate-500">
                  出力
                </p>
                <p className="mt-2 text-sm font-medium text-slate-900">最新エピソードをすぐ再生</p>
              </div>
            </div>
          </div>

          <GenerateEpisodeButton episodes={episodes} />
        </div>
      </section>

      {error && (
        <div className="mt-6 rounded-2xl border border-red-200 bg-red-50/90 p-4 text-sm text-red-700 shadow-sm">
          {error}
        </div>
      )}

      {!error && !latestEpisode && (
        <section className="mt-8 rounded-[2rem] border border-dashed border-slate-300 bg-white/70 px-6 py-16 text-center shadow-sm">
          <div className="mx-auto h-14 w-14 rounded-2xl border border-slate-200 bg-[linear-gradient(135deg,_#f8fafc,_#e2e8f0)]" />
          <p className="mt-5 text-lg font-semibold text-slate-900">まだエピソードがありません</p>
          <p className="mt-2 text-sm leading-7 text-slate-500">
            右上の生成カードから今日の番組を作成すると、ここに最新エピソードが表示されます。
          </p>
        </section>
      )}

      {!error && latestEpisode && (
        <section className="mt-8 grid gap-6 lg:grid-cols-[minmax(0,1.05fr)_minmax(320px,0.95fr)]">
          <div className="min-w-0 rounded-[2rem] border border-slate-200/80 bg-white/90 p-5 shadow-[0_18px_50px_rgba(15,23,42,0.08)] sm:p-6">
            <div className="flex flex-wrap items-start justify-between gap-3 min-w-0">
              <div>
                <p className="text-[11px] font-semibold uppercase tracking-[0.24em] text-slate-500">
                  Latest Episode
                </p>
                <h2 className="mt-3 text-2xl font-semibold text-slate-950 break-words">
                  {latestEpisode.title || `エピソード #${latestEpisode.id}`}
                </h2>
                {latestEpisode.subtitle && (
                  <p className="mt-2 text-sm leading-6 text-sky-700">{latestEpisode.subtitle}</p>
                )}
              </div>
              <span className="inline-flex rounded-full border border-emerald-200 bg-emerald-50 px-3 py-1 text-xs font-medium text-emerald-700">
                {formatDate(latestEpisode.date)}
              </span>
            </div>

            <p className="mt-4 max-w-2xl text-sm leading-7 text-slate-600">
              最新の生成結果です。再生しながら、必要なら一覧から過去の回との聞き比べもできます。
            </p>

            <div className="mt-6">
              {latestEpisode.audio_url ? (
                <AudioPlayer
                  src={buildAudioUrl(latestEpisode.audio_url)}
                  title={latestEpisode.title || `エピソード #${latestEpisode.id}`}
                />
              ) : (
                <div className="rounded-[1.5rem] border border-dashed border-slate-300 bg-slate-50 p-5 text-center text-sm text-slate-500">
                  音声ファイルを準備中です
                </div>
              )}
            </div>
          </div>

          {episodes.length > 0 && (
            <section className="min-w-0 rounded-[2rem] border border-slate-200/80 bg-white/90 p-5 shadow-[0_18px_50px_rgba(15,23,42,0.08)] sm:p-6">
              <div className="mb-4 flex items-center justify-between gap-3">
                <div>
                  <p className="text-[11px] font-semibold uppercase tracking-[0.24em] text-slate-500">
                    Archive
                  </p>
                  <h2 className="mt-2 text-xl font-semibold text-slate-950">過去のエピソード</h2>
                </div>
                <span className="rounded-full bg-slate-100 px-3 py-1 text-xs font-medium text-slate-600">
                  {episodes.length}件
                </span>
              </div>
              <EpisodeList episodes={episodes} />
            </section>
          )}
        </section>
      )}
    </main>
  )
}
