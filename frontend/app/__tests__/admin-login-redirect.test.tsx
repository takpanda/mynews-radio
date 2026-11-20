import '@testing-library/jest-dom'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import AdminLoginPage from '../admin/login/page'

const push = jest.fn()
const refresh = jest.fn()
jest.mock('next/navigation', () => ({ useRouter: () => ({ push, refresh }) }))

describe('管理画面ログイン', () => {
  beforeEach(() => jest.clearAllMocks())

  it('ログイン成功後は /admin/dashboard へ遷移する', async () => {
    global.fetch = jest.fn().mockResolvedValue({ ok: true })
    const user = userEvent.setup()
    render(<AdminLoginPage />)
    await user.type(screen.getByPlaceholderText('ユーザー名'), 'owner')
    await user.type(screen.getByPlaceholderText('パスワード'), 'pw')
    await user.click(screen.getByRole('button', { name: 'ログイン' }))
    await waitFor(() => expect(push).toHaveBeenCalledWith('/admin/dashboard'))
  })

  it('ログイン失敗時は遷移せずエラーを表示する', async () => {
    global.fetch = jest.fn().mockResolvedValue({ ok: false })
    const user = userEvent.setup()
    render(<AdminLoginPage />)
    await user.type(screen.getByPlaceholderText('ユーザー名'), 'owner')
    await user.type(screen.getByPlaceholderText('パスワード'), 'bad')
    await user.click(screen.getByRole('button', { name: 'ログイン' }))
    expect(await screen.findByText('ユーザー名またはパスワードが正しくありません')).toBeInTheDocument()
    expect(push).not.toHaveBeenCalled()
  })
})
