import AdminProgramFormShell from '../../../components/AdminProgramFormShell'
import AdminNav from '../../../components/AdminNav'
import { requireAdminSessionForPage } from '../../auth'
import { fetchMcs, type ProgramDefinitionValue } from '../../../lib/admin-programs'

const EMPTY_PROGRAM: ProgramDefinitionValue = {
  id: '',
  name: '',
  kind: 'radio',
  cast: [],
  segments: [],
  options: { style: null, mc_gender: null, narrative_arc: false, review_mode: 'on_failure' },
}

export default async function AdminNewProgramPage() {
  await requireAdminSessionForPage()
  let mcs: Awaited<ReturnType<typeof fetchMcs>> = []
  let error: string | null = null

  try {
    mcs = await fetchMcs(true)
  } catch {
    error = 'エラーが発生しました。しばらく後でもう一度お試しください。'
  }

  return (
    <main className="mx-auto max-w-5xl px-4 pb-24 pt-6 sm:px-6">
      <AdminNav />
      {error ? (
        <div className="rounded-2xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">{error}</div>
      ) : (
        <AdminProgramFormShell mode="create" initialProgram={EMPTY_PROGRAM} initialIsActive={true} mcs={mcs} />
      )}
    </main>
  )
}
