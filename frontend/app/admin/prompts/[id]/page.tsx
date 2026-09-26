import AdminPromptDetailShell from '../../../components/AdminPromptDetailShell'
import AdminNav from '../../../components/AdminNav'
import { requireAdminSessionForPage } from '../../auth'
import { fetchPrompts, fetchPromptVersions } from '../../../lib/admin-prompts'
import { fetchProgram, fetchPrograms, type ProgramKind } from '../../../lib/admin-programs'

export default async function AdminPromptDetailPage({ params }: { params: Promise<{ id: string }> }) {
  await requireAdminSessionForPage()
  const { id } = await params
  const promptId = Number(id)

  let error: string | null = null
  let template: Awaited<ReturnType<typeof fetchPrompts>>[number] | null = null
  let versionsData: Awaited<ReturnType<typeof fetchPromptVersions>> | null = null
  let programName: string | null = null
  let programKind: ProgramKind | null = null
  let radioPrograms: { id: string; name: string }[] = []
  let radioProgramsError = false

  if (!Number.isInteger(promptId) || promptId <= 0) {
    error = 'プロンプトが見つかりませんでした。'
  } else {
    try {
      const [templates, versions] = await Promise.all([fetchPrompts(), fetchPromptVersions(promptId)])
      template = templates.find((t) => t.id === promptId) ?? null
      versionsData = versions
      if (!template) {
        error = 'プロンプトが見つかりませんでした。'
      } else if (template.program_id) {
        try {
          const program = await fetchProgram(template.program_id)
          programName = program.name
          programKind = program.kind
        } catch {
          programName = null
        }
      } else if (template.template_key === 'generate_radio_script') {
        try {
          const programs = await fetchPrograms(false)
          radioPrograms = programs.filter((p) => p.kind === 'radio').map((p) => ({ id: p.id, name: p.name }))
        } catch {
          radioPrograms = []
          radioProgramsError = true
        }
      }
    } catch (err) {
      error = err instanceof Error ? err.message : 'エラーが発生しました。しばらく後でもう一度お試しください。'
    }
  }

  return (
    <main className="mx-auto max-w-5xl px-4 pb-24 pt-6 sm:px-6">
      <AdminNav />
      {error || !template || !versionsData ? (
        <div className="rounded-2xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">
          {error ?? 'プロンプトが見つかりませんでした。'}
        </div>
      ) : (
        <AdminPromptDetailShell
          promptId={promptId}
          templateKey={template.template_key}
          programId={template.program_id}
          programName={programName}
          programKind={programKind}
          radioPrograms={radioPrograms}
          radioProgramsError={radioProgramsError}
          requiredVariables={template.required_variables}
          allowedVariables={template.allowed_variables}
          initialVersions={versionsData.versions}
        />
      )}
    </main>
  )
}
