import AdminNav from '../../components/AdminNav'
import AdminDashboardShell from '../../components/AdminDashboardShell'
import { fetchDashboardStats } from '../../lib/admin-dashboard'
import { requireAdminSessionForPage } from '../auth'

export default async function AdminDashboardPage() {
  await requireAdminSessionForPage()
  let initialData: Awaited<ReturnType<typeof fetchDashboardStats>> | null = null
  let error: string | null = null

  try {
    initialData = await fetchDashboardStats('7d')
  } catch {
    error = 'エラーが発生しました。しばらく後でもう一度お試しください。'
  }

  return (
    <main className="mx-auto max-w-5xl px-4 pb-24 pt-6 sm:px-6">
      <AdminNav />
      {error ? (
        <>
          <h1 className="text-lg font-semibold text-slate-900">運用ダッシュボード</h1>
          <div role="alert" className="mt-4 rounded-2xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">
            {error}
          </div>
        </>
      ) : (
        <AdminDashboardShell initialData={initialData!} />
      )}
    </main>
  )
}
