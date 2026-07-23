'use client'

import Link from 'next/link'
import { useRouter } from 'next/navigation'

export default function AdminNav() {
  const router = useRouter()
  const logout = async () => {
    await fetch('/api/admin/logout', { method: 'POST' })
    router.push('/admin/login')
    router.refresh()
  }
  return (
    <nav className="mb-6 flex items-center gap-4 rounded-xl bg-slate-900 px-4 py-3 text-sm text-white">
      <span className="font-semibold">管理</span>
      <Link href="/admin/dictionary">辞書管理</Link>
      <Link href="/admin/misreading-reports">読み間違い報告</Link>
      <Link className="ml-auto" href="/">公開サイトへ</Link>
      <button type="button" onClick={logout}>ログアウト</button>
    </nav>
  )
}
