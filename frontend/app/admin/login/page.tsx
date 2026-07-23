'use client'

import { FormEvent, useState } from 'react'
import { useRouter } from 'next/navigation'

export default function AdminLoginPage() {
  const router = useRouter()
  const [error, setError] = useState('')
  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const data = new FormData(event.currentTarget)
    const response = await fetch('/api/admin/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username: data.get('username'), password: data.get('password') }),
    })
    if (!response.ok) {
      setError('ユーザー名またはパスワードが正しくありません')
      return
    }
    router.push('/admin/dictionary')
    router.refresh()
  }
  return (
    <main className="mx-auto max-w-md px-4 py-16">
      <h1 className="mb-6 text-2xl font-semibold">管理画面ログイン</h1>
      <form className="space-y-4" onSubmit={submit}>
        <input name="username" required placeholder="ユーザー名" className="w-full rounded border p-2" />
        <input name="password" required type="password" placeholder="パスワード" className="w-full rounded border p-2" />
        {error && <p className="text-sm text-red-600">{error}</p>}
        <button className="w-full rounded bg-slate-900 p-2 text-white" type="submit">ログイン</button>
      </form>
    </main>
  )
}
