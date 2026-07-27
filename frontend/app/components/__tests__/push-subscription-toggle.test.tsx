import '@testing-library/jest-dom'

import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import PushSubscriptionToggle from '../PushSubscriptionToggle'

const mockGetState = jest.fn()
const mockRegister = jest.fn()
const mockUnregister = jest.fn()
const mockIsSupported = jest.fn()

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
    await waitFor(() => expect(screen.getByText('通知ON')).toBeInTheDocument())
  })

  it('shows unsupported state', async () => {
    mockGetState.mockResolvedValue({ status: 'unsupported', subscriptionId: null })
    render(<PushSubscriptionToggle />)
    await waitFor(() => expect(screen.getByText('通知に対応していません')).toBeInTheDocument())
  })

  it('shows denied state', async () => {
    mockGetState.mockResolvedValue({ status: 'denied', subscriptionId: null })
    render(<PushSubscriptionToggle />)
    await waitFor(() => expect(screen.getByText('通知オフ')).toBeInTheDocument())
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

    await waitFor(() => expect(screen.getByText('通知ON')).toBeInTheDocument())
    await user.click(screen.getByRole('button'))
    await waitFor(() => expect(mockUnregister).toHaveBeenCalled())
  })

  it('keeps subscribed state when unregister throws (allows retry)', async () => {
    mockGetState.mockResolvedValue({ status: 'subscribed', subscriptionId: 'sub-id' })
    mockUnregister.mockRejectedValue(new Error('サーバーでの購読解除に失敗しました'))

    const user = userEvent.setup()
    render(<PushSubscriptionToggle />)

    await waitFor(() => expect(screen.getByText('通知ON')).toBeInTheDocument())
    await user.click(screen.getByRole('button'))
    await waitFor(() => expect(mockUnregister).toHaveBeenCalled())

    // State should still show "通知ON" because refreshState() is not called on error
    // The user can click again to retry
    expect(screen.getByText('通知ON')).toBeInTheDocument()
  })

  it('does not render button when unsupported (shows text instead)', async () => {
    mockGetState.mockResolvedValue({ status: 'unsupported', subscriptionId: null })
    render(<PushSubscriptionToggle />)
    await waitFor(() => expect(screen.getByText('通知に対応していません')).toBeInTheDocument())
    expect(screen.queryByRole('button')).not.toBeInTheDocument()
  })
})
