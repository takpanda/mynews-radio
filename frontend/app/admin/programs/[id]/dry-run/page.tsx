import AdminDryRunShell from '../../../../components/AdminDryRunShell'
import AdminNav from '../../../../components/AdminNav'
import { requireAdminSessionForPage } from '../../../auth'
import { fetchProgram } from '../../../../lib/admin-programs'

export default async function AdminProgramDryRunPage({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>
  searchParams: Promise<{ dry_run_id?: string; draft_prompt_version_id?: string }>
}) {
  await requireAdminSessionForPage()
  const { id } = await params
  const { dry_run_id: dryRunIdParam, draft_prompt_version_id: draftPromptVersionIdParam } = await searchParams
  let error: string | null = null
  let program: Awaited<ReturnType<typeof fetchProgram>> | null = null

  try {
    program = await fetchProgram(id)
  } catch (err) {
    error = err instanceof Error ? err.message : 'エラーが発生しました。しばらく後でもう一度お試しください。'
  }

  const initialDryRunId = dryRunIdParam && /^\d+$/.test(dryRunIdParam) ? Number(dryRunIdParam) : null
  const initialPromptVersionId =
    draftPromptVersionIdParam && /^\d+$/.test(draftPromptVersionIdParam) ? Number(draftPromptVersionIdParam) : null

  return (
    <main className="mx-auto max-w-5xl px-4 pb-24 pt-6 sm:px-6">
      <AdminNav />
      {error || !program ? (
        <div className="rounded-2xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">
          {error ?? '番組が見つかりませんでした。'}
        </div>
      ) : (
        <AdminDryRunShell
          programId={program.id}
          programKind={program.kind}
          currentDefinition={program.definition}
          initialDryRunId={initialDryRunId}
          initialPromptVersionId={initialPromptVersionId}
        />
      )}
    </main>
  )
}
