import AdminMisreadingReportsShell from '../../components/AdminMisreadingReportsShell'
import { fetchAdminMisreadingReports } from '../../lib/admin-misreading-reports'
import { cookies } from 'next/headers'
import { redirect } from 'next/navigation'
import AdminNav from '../../components/AdminNav'

export default async function AdminMisreadingReportsPage() {
  const cookie = cookies().get('admin_session')?.value
  if (!cookie) redirect('/admin/login')
  let initialData: Awaited<ReturnType<typeof fetchAdminMisreadingReports>> | null = null
  let error: string | null = null

  try {
    initialData = await fetchAdminMisreadingReports()
  } catch {
    error = 'エラーが発生しました。しばらく後でもう一度お試しください。'
  }

  return (
    <main className="mx-auto max-w-5xl px-4 pb-24 pt-6 sm:px-6">
      <AdminNav />
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
