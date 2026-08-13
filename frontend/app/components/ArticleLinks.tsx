import type { Article } from '../lib/api'
import { extractDomain } from '../lib/url'

interface Props {
  articles: Article[]
  sourceUrl?: string | null
  onReportArticle?: (article: Article) => void
}

function LinkIcon() {
  return (
    <svg
      aria-hidden="true"
      viewBox="0 0 24 24"
      className="mt-0.5 h-4 w-4 shrink-0 text-slate-400"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71" />
      <path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71" />
    </svg>
  )
}

function ArticleActions({ article, onReport }: { article: Article; onReport: (a: Article) => void }) {
  return (
    <button
      type="button"
      onClick={() => onReport(article)}
      className="flex items-center gap-1 rounded-full px-2 py-1 text-xs text-slate-400 transition hover:bg-slate-100 hover:text-slate-700"
      title="読み間違いを報告"
    >
      <svg
        aria-hidden="true"
        viewBox="0 0 24 24"
        className="h-3.5 w-3.5"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      >
        <path d="M12 20h9" />
        <path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z" />
      </svg>
      報告
    </button>
  )
}

function ArticleLinkContent({
  title,
  domain,
  source,
}: {
  title?: string | null
  domain: string | null
  source?: string | null
}) {
  const trimmedTitle = title?.trim()
  const primaryText = trimmedTitle || domain || 'リンク先'
  const metaParts = [
    ...(trimmedTitle && domain ? [domain] : []),
    ...(source?.trim() ? [source.trim()] : []),
  ]

  return (
    <>
      <LinkIcon />
      <div className="min-w-0">
        <p className="text-sm font-medium text-slate-900 line-clamp-2 hover:underline">
          {primaryText}
        </p>
        {metaParts.length > 0 && (
          <p className="mt-0.5 truncate text-xs text-slate-400">{metaParts.join(' ・ ')}</p>
        )}
      </div>
    </>
  )
}

export default function ArticleLinks({ articles, sourceUrl, onReportArticle }: Props) {
  const articlesWithUrl = articles.filter((a) => a.url)

  if (articlesWithUrl.length === 0 && !sourceUrl) return null

  return (
    <div className="rounded-2xl border border-slate-200 bg-white px-4 shadow-sm sm:px-5">
      {sourceUrl && (
        <a
          href={sourceUrl}
          target="_blank"
          rel="noopener noreferrer"
          className="flex items-start gap-3 border-b border-slate-100 py-3.5 transition last:border-b-0 hover:bg-slate-50"
        >
          <ArticleLinkContent domain={extractDomain(sourceUrl)} />
        </a>
      )}
      {articlesWithUrl.map((article) => (
        <div
          key={article.id}
          className="group flex items-start gap-3 border-b border-slate-100 py-3.5 transition last:border-b-0 hover:bg-slate-50"
        >
          <a
            href={article.url!}
            target="_blank"
            rel="noopener noreferrer"
            className="flex min-w-0 flex-1 items-start gap-3"
          >
            <ArticleLinkContent
              title={article.title}
              domain={extractDomain(article.url!)}
              source={article.source}
            />
          </a>
          {onReportArticle && (
            <div className="shrink-0 opacity-60 group-hover:opacity-100 group-focus-within:opacity-100 transition-opacity">
              <ArticleActions article={article} onReport={onReportArticle} />
            </div>
          )}
        </div>
      ))}
    </div>
  )
}
