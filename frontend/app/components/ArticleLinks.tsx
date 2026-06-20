import type { Article } from '../lib/api'

interface Props {
  articles: Article[]
  sourceUrl?: string | null
}

export default function ArticleLinks({ articles, sourceUrl }: Props) {
  const articlesWithUrl = articles.filter((a) => a.url)

  if (articlesWithUrl.length === 0 && !sourceUrl) return null

  return (
    <div className="space-y-2">
      {sourceUrl && (
        <a
          href={sourceUrl}
          target="_blank"
          rel="noopener noreferrer"
          className="flex items-start gap-3 bg-white rounded-xl p-4 shadow-sm hover:shadow-md transition-shadow border border-violet-100"
        >
          <span className="text-gray-400 mt-0.5 flex-shrink-0 text-lg">🔗</span>
          <div className="min-w-0">
            <p className="text-sm font-medium text-blue-600 line-clamp-2 hover:underline break-all">
              {sourceUrl}
            </p>
            <p className="text-xs text-gray-400 mt-1">解説元URL</p>
          </div>
        </a>
      )}
      {articlesWithUrl.map((article) => (
        <a
          key={article.id}
          href={article.url!}
          target="_blank"
          rel="noopener noreferrer"
          className="flex items-start gap-3 bg-white rounded-xl p-4 shadow-sm hover:shadow-md transition-shadow"
        >
          <span className="text-gray-400 mt-0.5 flex-shrink-0 text-lg">🔗</span>
          <div className="min-w-0">
            <p className="text-sm font-medium text-blue-600 line-clamp-2 hover:underline">
              {article.title}
            </p>
            {article.source && (
              <p className="text-xs text-gray-400 mt-1">{article.source}</p>
            )}
          </div>
        </a>
      ))}
    </div>
  )
}
