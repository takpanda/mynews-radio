import type { Metadata } from 'next'
import './globals.css'
import { Toaster } from 'react-hot-toast'
import SiteHeader from './components/SiteHeader'

export const metadata: Metadata = {
  title: 'MyNews Radio',
  description: 'あなた専用のニュース番組',
}

export default function RootLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <html lang="ja">
      <body className="min-h-screen">
        <SiteHeader />
        {children}
        <Toaster position="top-center" toastOptions={{ duration: 4000 }} />
      </body>
    </html>
  )
}
