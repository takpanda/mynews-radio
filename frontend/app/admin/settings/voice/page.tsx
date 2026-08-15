import AdminVoiceSettingsShell from '../../../components/AdminVoiceSettingsShell'
import { fetchVoiceOptions, fetchVoiceSettings } from '../../../lib/admin-voice-settings'
import AdminNav from '../../../components/AdminNav'
import { requireAdminSessionForPage } from '../../auth'

export default async function AdminVoiceSettingsPage() {
  await requireAdminSessionForPage()
  let initialSettings: Awaited<ReturnType<typeof fetchVoiceSettings>> | null = null
  let initialOptions: Awaited<ReturnType<typeof fetchVoiceOptions>> | null = null
  let error: string | null = null

  try {
    ;[initialSettings, initialOptions] = await Promise.all([fetchVoiceSettings(), fetchVoiceOptions()])
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
        <AdminVoiceSettingsShell initialSettings={initialSettings!} initialOptions={initialOptions!} />
      )}
    </main>
  )
}
