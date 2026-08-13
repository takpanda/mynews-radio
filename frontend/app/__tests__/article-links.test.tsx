import '@testing-library/jest-dom'
import React from 'react'

import { render, screen } from '@testing-library/react'
import ArticleLinks from '../components/ArticleLinks'
import type { Article } from '../lib/api'

function createArticle(overrides: Partial<Article> = {}): Article {
  return {
    id: 1,
    title: 'テスト記事タイトル',
    source: null,
    url: 'https://www.example.co.jp/news/123',
    ...overrides,
  }
}

describe('ArticleLinks', () => {
  it('記事タイトルをドメインより強調して表示する', () => {
    render(<ArticleLinks articles={[createArticle()]} sourceUrl={null} />)

    const titleEl = screen.getByText('テスト記事タイトル')
    expect(titleEl).toHaveClass('font-medium')
    expect(screen.getByText('example.co.jp')).toBeInTheDocument()
  })

  it('URL全体をテキストとして表示せず、リンク先としてのみ保持する', () => {
    render(<ArticleLinks articles={[createArticle()]} sourceUrl={null} />)

    expect(screen.queryByText('https://www.example.co.jp/news/123')).not.toBeInTheDocument()
    const link = screen.getByText('テスト記事タイトル').closest('a')
    expect(link).toHaveAttribute('href', 'https://www.example.co.jp/news/123')
    expect(link).toHaveAttribute('target', '_blank')
    expect(link).toHaveAttribute('rel', 'noopener noreferrer')
  })

  it('媒体名がある場合はドメインと併記して補助表示する', () => {
    render(<ArticleLinks articles={[createArticle({ source: 'テスト新聞' })]} sourceUrl={null} />)

    expect(screen.getByText('example.co.jp ・ テスト新聞')).toBeInTheDocument()
  })

  it('媒体名がない場合は推測値を表示しない', () => {
    render(<ArticleLinks articles={[createArticle({ source: null })]} sourceUrl={null} />)

    expect(screen.getByText('example.co.jp')).toBeInTheDocument()
    expect(screen.queryByText(/取得日時|不明/)).not.toBeInTheDocument()
  })

  it('URLが不正でドメインを抽出できない場合も画面が崩れない', () => {
    render(<ArticleLinks articles={[createArticle({ url: 'not-a-valid-url', source: null })]} sourceUrl={null} />)

    const link = screen.getByText('テスト記事タイトル').closest('a')
    expect(link).toHaveAttribute('href', 'not-a-valid-url')
    expect(screen.queryByText('not-a-valid-url')).not.toBeInTheDocument()
  })

  it('単一URLの解説回でも同じ表示部品でドメインを表示する', () => {
    render(<ArticleLinks articles={[]} sourceUrl="https://www.commentary-source.example/article" />)

    const domainEl = screen.getByText('commentary-source.example')
    expect(domainEl).toHaveClass('font-medium')
    const link = domainEl.closest('a')
    expect(link).toHaveAttribute('href', 'https://www.commentary-source.example/article')
    expect(screen.queryByText('https://www.commentary-source.example/article')).not.toBeInTheDocument()
  })

  it('記事とsourceUrlが両方なければ何も表示しない', () => {
    const { container } = render(<ArticleLinks articles={[]} sourceUrl={null} />)
    expect(container).toBeEmptyDOMElement()
  })
})
