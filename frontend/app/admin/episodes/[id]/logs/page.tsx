import { notFound } from 'next/navigation'
import AdminEpisodeLogsShell from '../../../../components/AdminEpisodeLogsShell'
import { fetchAdminEpisodeLogs } from '../../../../lib/admin-episode-logs'
import AdminNav from '../../../../components/AdminNav'
import { requireAdminSessionForPage } from '../../../auth'

interface Props {
  params: { id: string }
}

export default async function AdminEpisodeLogsPage({ params }: Props) {
  await requireAdminSessionForPage()

  const episodeId = parseInt(params.id, 10)
  if (isNaN(episodeId)) notFound()

  let initialData = null
  let error: string | null = null

  try {
    initialData = await fetchAdminEpisodeLogs(episodeId)
  } catch {
    error = 'エラーが発生しました。しばらく後でもう一度お試しください。'
  }

  if (!initialData && !error) notFound()

  return (
    <main className="mx-auto max-w-5xl px-4 pb-24 pt-6 sm:px-6">
      <AdminNav />
      {error ? (
        <div className="rounded-2xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">
          {error}
        </div>
      ) : (
        <AdminEpisodeLogsShell episodeId={episodeId} initialData={initialData!} />
      )}
    </main>
  )
}
