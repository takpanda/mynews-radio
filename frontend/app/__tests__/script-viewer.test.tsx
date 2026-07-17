import '@testing-library/jest-dom'

import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import ScriptViewer from '../components/ScriptViewer'
import type { ScriptLine } from '../lib/api'

beforeAll(() => {
  Element.prototype.scrollIntoView = jest.fn()
})

function setMobileViewport(width = 375, height = 667) {
  Object.defineProperty(window, 'innerWidth', { writable: true, configurable: true, value: width })
  Object.defineProperty(window, 'innerHeight', { writable: true, configurable: true, value: height })
  window.dispatchEvent(new Event('resize'))
}

const lines: ScriptLine[] = [
  { speaker: 'male', text: '最初の行です', article_id: null, section: 'intro', start_time: 0 },
  { speaker: 'female', text: '二番目の行です', article_id: 100, section: 'news', start_time: 10 },
  { speaker: 'male', text: '三番目の行です', article_id: null, section: 'news' },
]

describe('ScriptViewer', () => {
  describe('報告アイコン', () => {
    it('onMisreadingReportが提供されない場合アイコンを表示しない', () => {
      render(<ScriptViewer lines={lines} />)
      expect(screen.queryByRole('button')).not.toBeInTheDocument()
    })

    it('onMisreadingReportが提供された場合各行に報告アイコンを表示する', () => {
      render(<ScriptViewer lines={lines} onMisreadingReport={jest.fn()} />)
      const buttons = screen.getAllByRole('button')
      expect(buttons.length).toBe(lines.length)
      buttons.forEach((btn, i) => {
        expect(btn).toHaveAttribute('aria-label', expect.stringContaining('この行を報告'))
        expect(btn).toContainHTML('svg')
      })
    })

    it('タップ時に該当行の本文と共にonMisreadingReportを呼ぶ', async () => {
      const onReport = jest.fn()
      const user = userEvent.setup()
      render(<ScriptViewer lines={lines} onMisreadingReport={onReport} />)

      const buttons = screen.getAllByRole('button')
      await user.click(buttons[1])

      expect(onReport).toHaveBeenCalledTimes(1)
      expect(onReport).toHaveBeenCalledWith(
        expect.objectContaining({ text: '二番目の行です', speaker: 'female', article_id: 100 })
      )
    })

    it('アイコン操作で台本のシークが発火しない', async () => {
      const onSeek = jest.fn()
      const onReport = jest.fn()
      const user = userEvent.setup()
      render(
        <ScriptViewer
          lines={lines}
          currentTime={5}
          onSeek={onSeek}
          onMisreadingReport={onReport}
        />
      )

      const buttons = screen.getAllByRole('button')
      await user.click(buttons[0])

      expect(onReport).toHaveBeenCalledTimes(1)
      expect(onSeek).not.toHaveBeenCalled()
    })

    it('男性行と女性行の両方でアイコンが表示される', () => {
      render(<ScriptViewer lines={lines} onMisreadingReport={jest.fn()} />)
      expect(screen.getAllByRole('button').length).toBe(3)
    })
  })

  describe('モバイル幅表示（375px）', () => {
    beforeEach(() => setMobileViewport(375, 667))

    it('アイコンボタンがすべての行に存在する', () => {
      render(<ScriptViewer lines={lines} onMisreadingReport={jest.fn()} />)
      const buttons = screen.getAllByRole('button')
      expect(buttons.length).toBe(lines.length)
      buttons.forEach((btn) => {
        expect(btn).toHaveAttribute('aria-label', expect.stringContaining('この行を報告'))
        expect(btn).toBeVisible()
      })
    })

    it('台本のテキストが表示されている', () => {
      render(<ScriptViewer lines={lines} onMisreadingReport={jest.fn()} />)
      expect(screen.getByText('最初の行です')).toBeInTheDocument()
      expect(screen.getByText('二番目の行です')).toBeInTheDocument()
      expect(screen.getByText('三番目の行です')).toBeInTheDocument()
    })
  })

  describe('既存動作の回帰', () => {
    it('台本がない場合は「台本がありません」を表示する', () => {
      render(<ScriptViewer lines={[]} />)
      expect(screen.getByText('台本がありません')).toBeInTheDocument()
    })

    it('onSeekがある行をクリックするとシークが呼ばれる', async () => {
      const onSeek = jest.fn()
      const user = userEvent.setup()
      render(
        <ScriptViewer lines={lines} currentTime={5} onSeek={onSeek} />
      )

      const bubbles = screen.getAllByText(/行です/)
      await user.click(bubbles[0])

      expect(onSeek).toHaveBeenCalledWith(0)
    })

    it('start_timeがない行をクリックしてもシークは呼ばれない', async () => {
      const onSeek = jest.fn()
      const user = userEvent.setup()
      render(
        <ScriptViewer lines={lines} currentTime={5} onSeek={onSeek} />
      )

      const bubbleTexts = screen.getAllByText(/行です/)
      const lastLineText = bubbleTexts[bubbleTexts.length - 1]
      await user.click(lastLineText)

      expect(onSeek).not.toHaveBeenCalled()
    })
  })
})
