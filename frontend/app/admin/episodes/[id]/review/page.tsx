import { notFound } from 'next/navigation'
import AdminNav from '../../../../components/AdminNav'
import AdminScriptReviewShell from '../../../../components/AdminScriptReviewShell'
import { fetchScript } from '../../../../lib/admin-script-review'
import { requireAdminSessionForPage } from '../../../auth'

interface Props {
  params: Promise<{ id: string }>
}

export default async function AdminEpisodeScriptReviewPage(props: Props) {
  const params = await props.params
  await requireAdminSessionForPage()

  const episodeId = parseInt(params.id, 10)
  if (isNaN(episodeId)) notFound()

  let initialData: Awaited<ReturnType<typeof fetchScript>> = null
  let error: string | null = null

  try {
    initialData = await fetchScript(episodeId)
  } catch {
    error = 'エラーが発生しました。しばらく後でもう一度お試しください。'
  }

  if (!initialData && !error) notFound()

  return (
    <main className="mx-auto max-w-3xl px-4 pb-24 pt-6 sm:px-6">
      <AdminNav />
      {error ? (
        <div className="rounded-2xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">{error}</div>
      ) : (
        <AdminScriptReviewShell
          episodeId={episodeId}
          initialRevision={initialData!.revision}
          initialScript={initialData!.script}
        />
      )}
    </main>
  )
}
