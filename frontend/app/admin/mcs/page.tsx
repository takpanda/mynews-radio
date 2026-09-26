import AdminMcsShell from '../../components/AdminMcsShell'
import AdminNav from '../../components/AdminNav'
import { requireAdminSessionForPage } from '../auth'
import { fetchMcs } from '../../lib/admin-programs'

export default async function AdminMcsPage() {
  await requireAdminSessionForPage()
  let mcs: Awaited<ReturnType<typeof fetchMcs>> = []
  let error: string | null = null

  try {
    mcs = await fetchMcs(false)
  } catch {
    error = 'エラーが発生しました。しばらく後でもう一度お試しください。'
  }

  return (
    <main className="mx-auto max-w-5xl px-4 pb-24 pt-6 sm:px-6">
      <AdminNav />
      {error ? (
        <div className="rounded-2xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">{error}</div>
      ) : (
        <AdminMcsShell initialMcs={mcs} initialIncludeInactive={false} />
      )}
    </main>
  )
}
