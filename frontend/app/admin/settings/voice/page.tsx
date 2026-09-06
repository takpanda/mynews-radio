import AdminVoiceSettingsShell from '../../../components/AdminVoiceSettingsShell'
import CategoryFemaleMcSection from '../../../components/CategoryFemaleMcSection'
import FemaleMcCandidatesSection from '../../../components/FemaleMcCandidatesSection'
import { fetchVoiceOptions, fetchVoiceSettings } from '../../../lib/admin-voice-settings'
import { fetchCategoryFemaleMc } from '../../../lib/admin-category-female-mc'
import { fetchFemaleMcCandidates } from '../../../lib/admin-female-mc-candidates'
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

  let initialCategoryFemaleMc: Awaited<ReturnType<typeof fetchCategoryFemaleMc>> | null = null
  let categoryError: string | null = null
  try {
    initialCategoryFemaleMc = await fetchCategoryFemaleMc()
  } catch {
    categoryError = 'カテゴリ別女性MC設定を取得できませんでした。しばらく後でもう一度お試しください。'
  }

  let initialFemaleMcCandidates: Awaited<ReturnType<typeof fetchFemaleMcCandidates>> | null = null
  let candidatesError: string | null = null
  try {
    initialFemaleMcCandidates = await fetchFemaleMcCandidates()
  } catch {
    candidatesError = '女性MC候補マスタを取得できませんでした。しばらく後でもう一度お試しください。'
  }

  return (
    <main className="mx-auto max-w-5xl px-4 pb-24 pt-6 sm:px-6">
      <AdminNav />
      {error ? (
        <div className="rounded-2xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">
          {error}
        </div>
      ) : (
        <div className="space-y-6">
          <AdminVoiceSettingsShell initialSettings={initialSettings!} initialOptions={initialOptions!} />
          <CategoryFemaleMcSection initialData={initialCategoryFemaleMc} initialError={categoryError} />
          <FemaleMcCandidatesSection initialData={initialFemaleMcCandidates} initialError={candidatesError} />
        </div>
      )}
    </main>
  )
}
