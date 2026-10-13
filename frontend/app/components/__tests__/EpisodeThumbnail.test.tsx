import '@testing-library/jest-dom'

import { render } from '@testing-library/react'
import EpisodeThumbnail from '../EpisodeThumbnail'

const FALLBACK = '/images/categories/general.png'
const SRC = '/api/episodes/1/thumbnail'

// jsdom は画像を読み込まないため、マウント時点の complete / naturalWidth を差し替えて状態を再現する
function mockImageState(complete: boolean, naturalWidth: number) {
  jest.spyOn(HTMLImageElement.prototype, 'complete', 'get').mockReturnValue(complete)
  jest.spyOn(HTMLImageElement.prototype, 'naturalWidth', 'get').mockReturnValue(naturalWidth)
}

describe('EpisodeThumbnail マウント時の読み込み状態確認', () => {
  afterEach(() => jest.restoreAllMocks())

  it('onError 発火前でも、マウント時に complete=true かつ naturalWidth=0 ならフォールバックへ切り替える', () => {
    mockImageState(true, 0)
    const { container } = render(<EpisodeThumbnail src={SRC} fallbackSrc={FALLBACK} />)
    expect(container.querySelector('img')?.getAttribute('src')).toBe(FALLBACK)
  })

  it('読み込み中（complete=false）は元のURLを維持する', () => {
    mockImageState(false, 0)
    const { container } = render(<EpisodeThumbnail src={SRC} fallbackSrc={FALLBACK} />)
    expect(container.querySelector('img')?.getAttribute('src')).toBe(SRC)
  })

  it('読み込み成功済み（naturalWidth>0）は元のURLを維持する', () => {
    mockImageState(true, 1280)
    const { container } = render(<EpisodeThumbnail src={SRC} fallbackSrc={FALLBACK} />)
    expect(container.querySelector('img')?.getAttribute('src')).toBe(SRC)
  })

  it('src が無い場合はフォールバックを表示する', () => {
    const { container } = render(<EpisodeThumbnail src={null} fallbackSrc={FALLBACK} />)
    expect(container.querySelector('img')?.getAttribute('src')).toBe(FALLBACK)
  })
})
