import type { Metadata } from 'next'
import './globals.css'
import { Toaster } from 'react-hot-toast'
import SiteHeader from './components/SiteHeader'
import ServiceWorkerRegister from './components/ServiceWorkerRegister'
import { cookies } from 'next/headers'

export const metadata: Metadata = {
  title: 'MyNews Radio',
  description: 'あなた専用のニュース番組',
  manifest: '/manifest.json',
}

export default function RootLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <html lang="ja">
      <body className="min-h-screen">
        <SiteHeader isAuthenticated={Boolean(cookies().get('admin_session')?.value)} />
        {children}
        <ServiceWorkerRegister />
        <Toaster position="top-center" toastOptions={{ duration: 4000 }} />
      </body>
    </html>
  )
}
