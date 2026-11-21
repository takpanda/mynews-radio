// カテゴリ別のフォールバック画像。サムネイルの出し分けは保存済み categories を根拠にする（タイトル文字列は使わない）。
export type ThumbnailCategoryKey = 'tech' | 'general' | 'commentary' | 'digest'

export const CATEGORY_THUMBNAIL_IMAGE: Record<ThumbnailCategoryKey, string> = {
  general: '/images/categories/general.png',
  tech: '/images/categories/tech.jpg',
  commentary: '/images/categories/commentary.png',
  // ダイジェスト専用の画像は用意せず、一般と同じフォールバック画像を使う。
  digest: '/images/categories/general.png',
}

const TECH_CATEGORY_LABELS = new Set(['テック・IT', 'AI・先端技術'])

export function thumbnailCategoryKey(ep: { type?: string; categories?: string[] }): ThumbnailCategoryKey {
  if (ep.type === 'commentary') return 'commentary'
  if (ep.type === 'digest') return 'digest'
  if ((ep.categories ?? []).some((c) => TECH_CATEGORY_LABELS.has(c))) return 'tech'
  return 'general'
}
