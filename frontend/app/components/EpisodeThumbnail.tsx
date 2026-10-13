'use client'

import { useState } from 'react'

interface Props {
  /** APIが返す thumbnail_url。null／未設定ならフォールバック画像を表示する。 */
  src?: string | null
  /** サムネイルが無い・読み込み失敗時に表示する既存のカテゴリ別画像。 */
  fallbackSrc: string
  className?: string
}

// サムネイルがある回はその画像、無い（null/404）・読み込み失敗時はフォールバック画像を表示する。
// 親要素側でアスペクト比／高さを固定し、画像は absolute で埋めるためレイアウトは崩れない。
export default function EpisodeThumbnail({ src, fallbackSrc, className = '' }: Props) {
  const [failedSrc, setFailedSrc] = useState<string | null>(null)
  const useThumbnail = Boolean(src) && failedSrc !== src

  return (
    <img
      src={useThumbnail ? (src as string) : fallbackSrc}
      alt=""
      loading="lazy"
      decoding="async"
      onError={useThumbnail ? () => setFailedSrc(src ?? null) : undefined}
      className={`absolute inset-0 h-full w-full ${useThumbnail ? 'object-cover' : 'object-contain'} ${className}`.trim()}
    />
  )
}
