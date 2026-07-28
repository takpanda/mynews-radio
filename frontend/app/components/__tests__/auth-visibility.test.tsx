import '@testing-library/jest-dom'

import { render, screen } from '@testing-library/react'
import SiteHeader from '../SiteHeader'
import GenerateEpisodeButton from '../GenerateEpisodeButton'

jest.mock('next/navigation', () => ({
  useRouter: () => ({ refresh: jest.fn(), push: jest.fn() }),
}))
jest.mock('react-hot-toast', () => ({ toast: Object.assign(jest.fn(), { success: jest.fn() }) }))

describe('未認証時のオーナー操作UI', () => {
  it('ヘッダーは生成ボタンの代わりにログイン導線を表示する', () => {
    render(<SiteHeader isAuthenticated={false} />)
    expect(screen.queryByRole('button', { name: '番組を生成' })).not.toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'ログインして生成' })).toHaveAttribute('href', '/admin/login')
  })

  it('生成パネルは操作項目を表示せずログイン導線を表示する', () => {
    render(<GenerateEpisodeButton isAuthenticated={false} />)
    expect(screen.queryByRole('button', { name: /この設定で番組を生成/ })).not.toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'ログインする' })).toHaveAttribute('href', '/admin/login')
    expect(screen.getByText('公開アーカイブの閲覧と音声再生は、ログインなしで利用できます。')).toBeInTheDocument()
  })
})
