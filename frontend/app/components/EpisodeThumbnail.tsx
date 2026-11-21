'use client'

import { useEffect, useRef, useState } from 'react'

type ThumbnailSize = 'card' | 'detail'

interface Props {
  /** APIが返す thumbnail_url。null／未設定ならフォールバック画像を表示する。 */
  src?: string | null
  /** サムネイルが無い・読み込み失敗時に表示する既存のカテゴリ別画像。 */
  fallbackSrc: string
  /** 要求する軽量版のサイズ（一覧: card / 詳細: detail）。未指定なら従来どおりサイズ指定なし。 */
  size?: ThumbnailSize
  /** ファーストビューの画像。true なら lazy をやめ fetchpriority=high で優先読み込みする。 */
  priority?: boolean
  className?: string
}

// 軽量版WebPの最大幅（backend の card=640 / detail=1200）に合わせた 16:9 の固有サイズ。レイアウト確保用。
const DIMENSIONS: Record<ThumbnailSize, { width: number; height: number }> = {
  card: { width: 640, height: 360 },
  detail: { width: 1200, height: 675 },
}

function withSize(src: string, size?: ThumbnailSize) {
  if (!size) return src
  return `${src}${src.includes('?') ? '&' : '?'}size=${size}`
}

// サムネイルがある回はその画像、無い（null/404）・読み込み失敗時はフォールバック画像を表示する。
// 読み込み完了までは親の背景色が無地で見えないよう、スケルトン（パルス）を重ねる。
// スケルトンは画像の背面に置き、画像自体は常に表示状態にする（未読み込みの画像は透明なので背面のスケルトンが見える）。
// 画像を opacity-0 で隠すと、ハイドレーションが遅れる／失敗した場合にSSR済みの画像が永続的に見えなくなるため。
// 親要素側でアスペクト比／高さを固定し、画像は absolute で埋めるためレイアウトは崩れない。
export default function EpisodeThumbnail({ src, fallbackSrc, size, priority = false, className = '' }: Props) {
  const [failedSrc, setFailedSrc] = useState<string | null>(null)
  const [loadedSrc, setLoadedSrc] = useState<string | null>(null)
  const useThumbnail = Boolean(src) && failedSrc !== src
  const imgRef = useRef<HTMLImageElement>(null)
  const dimensions = DIMENSIONS[size ?? 'card']

  // SSR済みの画像がハイドレーション前に読み込み完了/失敗すると onLoad/onError を取りこぼすため、マウント時に状態を確認する。
  useEffect(() => {
    const img = imgRef.current
    if (!useThumbnail || !img || !img.complete) return
    if (img.naturalWidth === 0) setFailedSrc(src ?? null)
    else setLoadedSrc(src ?? null)
  }, [useThumbnail, src])

  // フォールバック画像は軽量な既存の静的画像のためスケルトン対象外。
  const showSkeleton = useThumbnail && loadedSrc !== src

  return (
    <>
      {showSkeleton && (
        <div
          data-testid="thumbnail-skeleton"
          aria-hidden="true"
          className="absolute inset-0 animate-pulse bg-slate-700/60 motion-reduce:animate-none"
        />
      )}
      <img
        ref={imgRef}
        src={useThumbnail ? withSize(src as string, size) : fallbackSrc}
        alt=""
        width={dimensions.width}
        height={dimensions.height}
        loading={priority ? 'eager' : 'lazy'}
        // Next 15 の App Router は React 19 で動くため camelCase（小文字の fetchpriority は Invalid DOM property になる）
        fetchPriority={priority ? 'high' : undefined}
        decoding="async"
        onLoad={useThumbnail ? () => setLoadedSrc(src ?? null) : undefined}
        onError={useThumbnail ? () => setFailedSrc(src ?? null) : undefined}
        className={`absolute inset-0 h-full w-full object-contain ${className}`.trim()}
      />
    </>
  )
}
