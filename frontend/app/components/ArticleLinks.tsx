import type { Article } from '../lib/api'

interface Props {
  articles: Article[]
  sourceUrl?: string | null
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

export default function ArticleLinks({ articles, sourceUrl }: Props) {
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
          <LinkIcon />
          <div className="min-w-0">
            <p className="break-all text-sm text-sky-700 line-clamp-2 hover:underline">
              {sourceUrl}
            </p>
            <p className="mt-0.5 text-xs text-slate-400">解説元URL</p>
          </div>
        </a>
      )}
      {articlesWithUrl.map((article) => (
        <a
          key={article.id}
          href={article.url!}
          target="_blank"
          rel="noopener noreferrer"
          className="flex items-start gap-3 border-b border-slate-100 py-3.5 transition last:border-b-0 hover:bg-slate-50"
        >
          <LinkIcon />
          <div className="min-w-0">
            <p className="text-sm text-sky-700 line-clamp-2 hover:underline">{article.title}</p>
            {article.source && <p className="mt-0.5 text-xs text-slate-400">{article.source}</p>}
          </div>
        </a>
      ))}
    </div>
  )
}
