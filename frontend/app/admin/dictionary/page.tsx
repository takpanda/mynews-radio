import AdminDictionaryShell from '../../components/AdminDictionaryShell'
import { fetchDictionaryEntries } from '../../lib/admin-dictionary'

export default async function AdminDictionaryPage() {
  let initialData = null
  let error: string | null = null

  try {
    initialData = await fetchDictionaryEntries({ limit: 20, offset: 0 })
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
        <AdminDictionaryShell initialData={initialData!} />
      )}
    </main>
  )
}
