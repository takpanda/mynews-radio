import AdminProgramFormShell from '../../../components/AdminProgramFormShell'
import AdminNav from '../../../components/AdminNav'
import { requireAdminSessionForPage } from '../../auth'
import { fetchMcs, fetchProgram } from '../../../lib/admin-programs'

export default async function AdminEditProgramPage({ params }: { params: Promise<{ id: string }> }) {
  await requireAdminSessionForPage()
  const { id } = await params
  let error: string | null = null
  let program: Awaited<ReturnType<typeof fetchProgram>> | null = null
  let mcs: Awaited<ReturnType<typeof fetchMcs>> = []

  try {
    ;[program, mcs] = await Promise.all([fetchProgram(id), fetchMcs(true)])
  } catch (err) {
    error = err instanceof Error ? err.message : 'エラーが発生しました。しばらく後でもう一度お試しください。'
  }

  return (
    <main className="mx-auto max-w-5xl px-4 pb-24 pt-6 sm:px-6">
      <AdminNav />
      {error || !program ? (
        <div className="rounded-2xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">
          {error ?? '番組が見つかりませんでした。'}
        </div>
      ) : (
        <AdminProgramFormShell
          mode="edit"
          initialProgram={program.definition}
          initialIsActive={program.is_active}
          mcs={mcs}
        />
      )}
    </main>
  )
}
