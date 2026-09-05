import '@testing-library/jest-dom'

import { fireEvent, render, screen } from '@testing-library/react'
import EpisodeAudioPlayer from '../EpisodeAudioPlayer'
import SiteHeader from '../SiteHeader'

jest.mock('next/navigation', () => ({
  useRouter: () => ({ refresh: jest.fn(), push: jest.fn() }),
}))

jest.mock('react-hot-toast', () => ({ toast: Object.assign(jest.fn(), { success: jest.fn() }) }))

jest.mock('../GenerateEpisodeButton', () => ({
  __esModule: true,
  default: () => <div />,
}))

describe('狭幅表示の回帰防止', () => {
  it('ヘッダーのロゴ・ナビゲーション文字列を折り返さない', () => {
    render(<SiteHeader isAuthenticated={false} />)

    expect(screen.getByText('MyNews Radio')).toHaveClass('whitespace-nowrap')
    expect(screen.getByRole('link', { name: 'アーカイブ' })).toHaveClass('whitespace-nowrap')
    expect(screen.getByRole('link', { name: '運営者ログイン' })).toHaveClass('whitespace-nowrap')
  })

  it('プレーヤーの時間と操作列を折り返さず、操作を実行できる', () => {
    const { container } = render(
      <EpisodeAudioPlayer audioUrl="/episodes/1.mp3" title="テスト番組" date="2026-08-14" durationSeconds={120} />,
    )
    const audio = container.querySelector('audio') as HTMLAudioElement
    const timeAndControls = screen.getByRole('button', { name: '15秒戻す' }).parentElement

    expect(screen.getAllByText('0:00 / 2:00')[0]).toHaveClass('whitespace-nowrap')
    expect(timeAndControls).toHaveClass('whitespace-nowrap')

    audio.currentTime = 20
    fireEvent.click(screen.getByRole('button', { name: '15秒戻す' }))
    expect(audio.currentTime).toBe(5)

    fireEvent.click(screen.getByRole('button', { name: '30秒進める' }))
    expect(audio.currentTime).toBe(35)

    fireEvent.click(screen.getByRole('button', { name: '再生速度 1倍' }))
    expect(screen.getByRole('button', { name: '再生速度 1.25倍' })).toBeInTheDocument()

    expect(screen.getByRole('link', { name: '音声をダウンロード' })).toHaveAttribute('download', '2026-08-14_テスト番組.mp3')
  })
})
