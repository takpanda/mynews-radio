import AdminMisreadingReportsShell from '../../components/AdminMisreadingReportsShell'
import { fetchAdminMisreadingReports } from '../../lib/admin-misreading-reports'

export default async function AdminMisreadingReportsPage() {
  let initialData: Awaited<ReturnType<typeof fetchAdminMisreadingReports>> | null = null
  let error: string | null = null

  try {
    initialData = await fetchAdminMisreadingReports()
  } catch {
    error = 'エラーが発生しました。しばらく後でもう一度お試しください。'
  }

  return (
    <main className="mx-auto max-w-5xl px-4 pb-24 pt-6 sm:px-6">
      {error ? (
        <div className="rounded-2xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">
          {error}
        </div>
      ) : (
        <AdminMisreadingReportsShell initialData={initialData!} />
      )}
    </main>
  )
}
