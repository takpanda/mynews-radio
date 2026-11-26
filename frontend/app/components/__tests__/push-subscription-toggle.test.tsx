import '@testing-library/jest-dom'

import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import PushSubscriptionToggle from '../PushSubscriptionToggle'

const mockGetState = jest.fn()
const mockRegister = jest.fn()
const mockUnregister = jest.fn()
const mockIsSupported = jest.fn()

const mockToast = Object.assign(jest.fn(), { success: jest.fn(), error: jest.fn() })
jest.mock('react-hot-toast', () => ({
  toast: Object.assign((...args: unknown[]) => mockToast(...args), {
    success: (...args: unknown[]) => mockToast.success(...args),
    error: (...args: unknown[]) => mockToast.error(...args),
  }),
}))

jest.mock('../../lib/push-subscription', () => ({
  getSubscriptionState: (...args: unknown[]) => mockGetState(...args),
  registerPushSubscription: (...args: unknown[]) => mockRegister(...args),
  unregisterPushSubscription: (...args: unknown[]) => mockUnregister(...args),
  isPushSupported: (...args: unknown[]) => mockIsSupported(...args),
}))

beforeEach(() => {
  jest.clearAllMocks()
  mockIsSupported.mockReturnValue(true)
  mockGetState.mockResolvedValue({ status: 'prompt', subscriptionId: null })
  mockRegister.mockResolvedValue({ status: 'subscribed', subscriptionId: 'sub-id' })
  mockUnregister.mockResolvedValue(undefined)
})

describe('PushSubscriptionToggle', () => {
  it('shows prompt state with subscribe button text', async () => {
    render(<PushSubscriptionToggle />)
    await waitFor(() => expect(screen.getByRole('button')).toBeInTheDocument())
    expect(screen.getByText('毎朝、完成を通知')).toBeInTheDocument()
  })

  it('shows subscribed state', async () => {
    mockGetState.mockResolvedValue({ status: 'subscribed', subscriptionId: 'sub-id' })
    render(<PushSubscriptionToggle />)
    await waitFor(() => expect(screen.getByText('通知オン（毎朝お知らせします）')).toBeInTheDocument())
  })

  it('shows unsupported state', async () => {
    mockGetState.mockResolvedValue({ status: 'unsupported', subscriptionId: null })
    render(<PushSubscriptionToggle />)
    await waitFor(() => expect(screen.getByText('通知に対応していません')).toBeInTheDocument())
  })

  it('shows denied state', async () => {
    mockGetState.mockResolvedValue({ status: 'denied', subscriptionId: null })
    render(<PushSubscriptionToggle />)
    await waitFor(() => expect(screen.getByText('通知がブロックされています')).toBeInTheDocument())
    const button = screen.getByRole('button')
    expect(button).toHaveAttribute('aria-pressed', 'false')
    expect(button).not.toBeDisabled()
    expect(button.className).not.toContain('cursor-not-allowed')
  })

  it('shows guidance toast when clicking in denied state', async () => {
    mockGetState.mockResolvedValue({ status: 'denied', subscriptionId: null })
    const user = userEvent.setup()
    render(<PushSubscriptionToggle />)
    await waitFor(() => expect(screen.getByText('通知がブロックされています')).toBeInTheDocument())
    await user.click(screen.getByRole('button'))
    expect(mockToast).toHaveBeenCalledWith(expect.stringContaining('鍵アイコン'), expect.anything())
    expect(mockRegister).not.toHaveBeenCalled()
  })

  it('shows success toast and on-label when subscribe succeeds', async () => {
    const user = userEvent.setup()
    render(<PushSubscriptionToggle />)
    await waitFor(() => expect(screen.getByText('毎朝、完成を通知')).toBeInTheDocument())
    await user.click(screen.getByRole('button'))
    await waitFor(() => expect(screen.getByText('通知オン（毎朝お知らせします）')).toBeInTheDocument())
    expect(mockToast.success).toHaveBeenCalledWith('通知をオンにしました')
    expect(screen.getByRole('button')).toHaveAttribute('aria-pressed', 'true')
  })

  it('shows blocked label and guidance (no success toast) when permission is blocked', async () => {
    mockRegister.mockResolvedValue({ status: 'denied', subscriptionId: null })
    const user = userEvent.setup()
    render(<PushSubscriptionToggle />)
    await waitFor(() => expect(screen.getByText('毎朝、完成を通知')).toBeInTheDocument())
    await user.click(screen.getByRole('button'))
    await waitFor(() => expect(screen.getByText('通知がブロックされています')).toBeInTheDocument())
    expect(mockToast.success).not.toHaveBeenCalled()
    expect(mockToast.error).toHaveBeenCalledWith(expect.stringContaining('鍵アイコン'), expect.anything())
  })

  it('returns to prompt label without toasts when dialog is dismissed', async () => {
    mockRegister.mockResolvedValue({ status: 'prompt', subscriptionId: null })
    const user = userEvent.setup()
    render(<PushSubscriptionToggle />)
    await waitFor(() => expect(screen.getByText('毎朝、完成を通知')).toBeInTheDocument())
    await user.click(screen.getByRole('button'))
    await waitFor(() => expect(mockRegister).toHaveBeenCalledTimes(1))
    expect(screen.getByText('毎朝、完成を通知')).toBeInTheDocument()
    expect(mockToast.success).not.toHaveBeenCalled()
    expect(mockToast.error).not.toHaveBeenCalled()
    await user.click(screen.getByRole('button'))
    await waitFor(() => expect(mockRegister).toHaveBeenCalledTimes(2))
  })

  it('shows 通知をオフにしました after unsubscribing', async () => {
    mockGetState.mockResolvedValue({ status: 'subscribed', subscriptionId: 'sub-id' })
    const user = userEvent.setup()
    render(<PushSubscriptionToggle />)
    await waitFor(() => expect(screen.getByText('通知オン（毎朝お知らせします）')).toBeInTheDocument())
    mockGetState.mockResolvedValue({ status: 'prompt', subscriptionId: null })
    await user.click(screen.getByRole('button'))
    await waitFor(() => expect(mockToast.success).toHaveBeenCalledWith('通知をオフにしました'))
  })

  it('subscribes on click when prompt state', async () => {
    const user = userEvent.setup()
    render(<PushSubscriptionToggle />)
    await waitFor(() => expect(screen.getByText('毎朝、完成を通知')).toBeInTheDocument())
    await user.click(screen.getByRole('button'))
    await waitFor(() => expect(mockRegister).toHaveBeenCalled())
  })

  it('unsubscribes on click when subscribed state', async () => {
    mockGetState.mockResolvedValue({ status: 'subscribed', subscriptionId: 'sub-id' })
    const user = userEvent.setup()
    render(<PushSubscriptionToggle />)

    await waitFor(() => expect(screen.getByText('通知オン（毎朝お知らせします）')).toBeInTheDocument())
    await user.click(screen.getByRole('button'))
    await waitFor(() => expect(mockUnregister).toHaveBeenCalled())
  })

  it('keeps subscribed state when unregister throws (allows retry)', async () => {
    mockGetState.mockResolvedValue({ status: 'subscribed', subscriptionId: 'sub-id' })
    mockUnregister.mockRejectedValue(new Error('サーバーでの購読解除に失敗しました'))

    const user = userEvent.setup()
    render(<PushSubscriptionToggle />)

    await waitFor(() => expect(screen.getByText('通知オン（毎朝お知らせします）')).toBeInTheDocument())
    await user.click(screen.getByRole('button'))
    await waitFor(() => expect(mockUnregister).toHaveBeenCalled())

    // State should still show "通知オン" because refreshState() is not called on error
    // The user can click again to retry
    expect(screen.getByText('通知オン（毎朝お知らせします）')).toBeInTheDocument()
  })

  it('does not render button when unsupported (shows text instead)', async () => {
    mockGetState.mockResolvedValue({ status: 'unsupported', subscriptionId: null })
    render(<PushSubscriptionToggle />)
    await waitFor(() => expect(screen.getByText('通知に対応していません')).toBeInTheDocument())
    expect(screen.queryByRole('button')).not.toBeInTheDocument()
  })
})
