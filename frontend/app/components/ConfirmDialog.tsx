'use client'

import { useEffect, useRef } from 'react'

interface Props {
  title: string
  message: string
  confirmLabel: string
  cancelLabel?: string
  confirming?: boolean
  danger?: boolean
  error?: string | null
  onConfirm: () => void
  onCancel: () => void
  children?: React.ReactNode
}

export default function ConfirmDialog({
  title,
  message,
  confirmLabel,
  cancelLabel = 'キャンセル',
  confirming = false,
  danger = false,
  error,
  onConfirm,
  onCancel,
  children,
}: Props) {
  const backdropRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && !confirming) onCancel()
    }
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [onCancel, confirming])

  const handleBackdropClick = (e: React.MouseEvent) => {
    if (e.target === backdropRef.current && !confirming) onCancel()
  }

  return (
    <div
      ref={backdropRef}
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4"
      onClick={handleBackdropClick}
    >
      <div
        className="flex w-full max-w-lg flex-col rounded-2xl border border-slate-200 bg-white shadow-xl"
        role="dialog"
        aria-modal="true"
        aria-labelledby="confirm-dialog-title"
      >
        <div className="flex items-center justify-between border-b border-slate-200 px-5 py-4">
          <h2 id="confirm-dialog-title" className="text-base font-semibold text-slate-900">
            {title}
          </h2>
          <button
            type="button"
            onClick={onCancel}
            disabled={confirming}
            className="flex h-8 w-8 items-center justify-center rounded-full text-slate-500 transition hover:bg-slate-100 hover:text-slate-800 disabled:opacity-50"
            aria-label="閉じる"
          >
            <svg aria-hidden="true" viewBox="0 0 24 24" className="h-4.5 w-4.5" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
              <path d="M6 6l12 12M18 6L6 18" />
            </svg>
          </button>
        </div>

        <div className="space-y-3 overflow-y-auto px-5 py-4">
          <p className="text-sm leading-6 text-slate-600">{message}</p>
          {children}
          {error && (
            <div className="rounded-xl border border-red-200 bg-red-50 p-3 text-sm text-red-700">{error}</div>
          )}
        </div>

        <div className="flex items-center justify-end gap-2 border-t border-slate-100 px-5 py-4">
          <button
            type="button"
            onClick={onCancel}
            disabled={confirming}
            className="min-h-11 rounded-full border border-slate-200 bg-white px-4 py-2 text-sm font-medium text-slate-700 transition hover:bg-slate-50 disabled:opacity-50"
          >
            {cancelLabel}
          </button>
          <button
            type="button"
            onClick={onConfirm}
            disabled={confirming}
            className={`inline-flex min-h-11 items-center gap-1.5 rounded-full px-5 py-2 text-sm font-medium text-white transition disabled:cursor-not-allowed disabled:opacity-60 ${
              danger ? 'bg-red-600 hover:bg-red-700' : 'bg-sky-600 hover:bg-sky-700'
            }`}
          >
            {confirming && (
              <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-white/30 border-t-white" />
            )}
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  )
}
