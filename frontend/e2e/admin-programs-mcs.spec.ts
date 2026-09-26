import { expect, test, type Page } from '@playwright/test'

const mockApi = 'http://127.0.0.1:8311'

async function login(page: Page) {
  await page.goto('/admin/login')
  await page.getByPlaceholder('ユーザー名').fill('admin')
  await page.getByPlaceholder('パスワード').fill('password')
  await page.getByRole('button', { name: 'ログイン' }).click()
  await expect(page).toHaveURL(/\/admin\/dictionary$/)
}

async function resetApi(page: Page) {
  const response = await page.request.post(`${mockApi}/__reset`)
  expect(response.ok()).toBeTruthy()
}

async function readMockState(page: Page) {
  const response = await page.request.get(`${mockApi}/__state`)
  return response.json() as Promise<{
    mutations: Array<{ method: string; resource: string; body: Record<string, unknown> }>
  }>
}

test.beforeEach(async ({ page }) => {
  await resetApi(page)
  await login(page)
})

test('375pxでは番組・MC一覧と番組詳細を閲覧でき、編集や追加の操作は隠れる', async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 })

  await page.goto('/admin/programs')
  await expect(page.getByRole('heading', { name: '番組管理' })).toBeVisible()
  await expect(page.getByText('朝のニュース')).toBeVisible()
  await expect(page.getByRole('link', { name: '番組を新規作成' })).toBeHidden()

  await page.goto('/admin/programs/morning')
  await expect(page.getByTestId('program-mobile-summary')).toBeVisible()
  await expect(page.getByTestId('program-edit-form')).toBeHidden()
  await expect(page.getByRole('button', { name: '保存する' })).toBeHidden()
  await expect(page.getByRole('button', { name: 'セグメントを追加' })).toBeHidden()

  await page.goto('/admin/programs/new')
  await expect(page.getByTestId('program-mobile-summary')).toBeVisible()
  await expect(page.getByTestId('program-edit-form')).toBeHidden()
  await expect(page.getByRole('button', { name: '作成する' })).toBeHidden()

  await page.goto('/admin/mcs')
  await expect(page.getByRole('heading', { name: 'MC管理' })).toBeVisible()
  await expect(page.getByText('青木')).toBeVisible()
  await expect(page.getByRole('button', { name: 'MCを追加' })).toBeHidden()
  await expect(page.getByRole('button', { name: '編集' }).first()).toBeHidden()
})

test('PC幅では番組編集・新規作成とMC追加・編集を操作できる', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 })

  await page.goto('/admin/programs')
  await expect(page.getByRole('link', { name: '番組を新規作成' })).toBeVisible()
  await page.goto('/admin/programs/morning')
  await expect(page.getByTestId('program-edit-form')).toBeVisible()
  await expect(page.getByTestId('program-mobile-summary')).toBeHidden()
  await expect(page.getByRole('button', { name: '保存する' })).toBeEnabled()
  await page.goto('/admin/programs/new')
  await expect(page.getByRole('button', { name: '作成する' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'キャストを追加' })).toBeVisible()

  await page.goto('/admin/mcs')
  await expect(page.getByRole('button', { name: 'MCを追加' })).toBeVisible()
  await expect(page.getByRole('button', { name: '編集' }).first()).toBeVisible()
})

test('セグメント上限、変更メモ必須、キャンセル、保存後の再読み込みを確認する', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 })
  await page.goto('/admin/programs/morning')

  await page.getByRole('button', { name: 'セグメントを追加' }).click()
  await expect(page.getByText('セグメント（6/6）')).toBeVisible()
  const segmentCards = page.locator(
    '[data-testid="program-edit-form"] .rounded-xl.border.border-slate-100.bg-slate-50',
  )
  await segmentCards.last().locator('input[type="text"]').first().fill('segment-6')
  await page.getByRole('button', { name: 'セグメントを追加' }).click()
  await expect(page.getByText('セグメントは最大6件までです')).toBeVisible()
  await expect(page.getByText('セグメント（6/6）')).toBeVisible()

  await page.getByRole('button', { name: 'segment-1番目のセグメントを下へ' }).click()
  await expect(page.getByRole('button', { name: 'segment-2番目のセグメントを上へ' })).toBeDisabled()

  await page.locator('[data-testid="program-edit-form"] input[type="text"]').nth(1).fill('朝のニュース 更新')
  await page.getByRole('button', { name: '保存する' }).click()
  const dialog = page.getByRole('dialog')
  await expect(dialog).toBeVisible()
  await page.getByRole('button', { name: '保存する' }).last().click()
  await expect(dialog.getByText('変更メモを入力してください', { exact: true })).toBeVisible()
  expect((await readMockState(page)).mutations).toHaveLength(0)

  await dialog.getByRole('button', { name: 'キャンセル' }).click()
  await expect(dialog).toBeHidden()
  expect((await readMockState(page)).mutations).toHaveLength(0)

  await page.getByRole('button', { name: '保存する' }).click()
  await page.getByLabel('変更メモ').fill('出演者と構成を更新')
  await page.getByRole('dialog').getByRole('button', { name: '保存する' }).click()
  await expect(page.getByText('番組を保存しました。変更はすぐに反映されます。')).toBeVisible()
  const mutations = (await readMockState(page)).mutations
  expect(mutations).toHaveLength(1)
  const savedSegments = (mutations[0].body.segments as Array<{ id: string; order: number }>)
  expect(savedSegments.map((segment) => segment.id)).toEqual([
    'segment-2', 'segment-1', 'segment-3', 'segment-4', 'segment-5', 'segment-6',
  ])
  const orders = savedSegments.map((segment) => segment.order)
  expect(new Set(orders).size).toBe(orders.length)
  expect(orders).toEqual([...orders].sort((a, b) => a - b))

  await page.reload()
  await expect(
    page.locator('[data-testid="program-edit-form"] input[type="text"]').nth(1),
  ).toHaveValue('朝のニュース 更新')
  await expect(page.getByText('セグメント（6/6）')).toBeVisible()
  await expect(page.getByRole('button', { name: 'segment-2番目のセグメントを上へ' })).toBeDisabled()
  await expect(page.getByRole('button', { name: 'segment-1番目のセグメントを上へ' })).toBeEnabled()
})

test('重複した番組IDの409エラーを画面に表示する', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 })
  await page.goto('/admin/programs/new')
  const inputs = page.locator('[data-testid="program-edit-form"] input[type="text"]')
  await inputs.nth(0).fill('morning')
  await inputs.nth(1).fill('重複番組')
  await page.getByRole('button', { name: 'キャストを追加' }).click()
  await inputs.nth(2).fill('host')
  await inputs.nth(3).fill('テストMC')
  await inputs.nth(4).fill('MC')
  await page.getByRole('button', { name: '作成する' }).click()
  await expect(page.getByText('番組IDは既に使用されています')).toBeVisible()

  await inputs.nth(0).fill('morning-two')
  await page.getByRole('button', { name: '作成する' }).click()
  await expect(page).toHaveURL(/\/admin\/programs\/morning-two$/)
  await expect(
    page.locator('[data-testid="program-edit-form"] input[type="text"]').nth(1),
  ).toHaveValue('重複番組')
})

test('無効なMC参照の422エラーを変更確認ダイアログに表示する', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 })
  await page.goto('/admin/programs/morning')
  await page.locator('[data-testid="program-edit-form"] select').nth(1).selectOption('mc-orphan')
  await page.getByRole('button', { name: '保存する' }).click()
  const dialog = page.getByRole('dialog')
  await dialog.getByLabel('変更メモ').fill('MC参照エラー確認')
  await dialog.getByRole('button', { name: '保存する' }).click()
  await expect(dialog.getByText('MC参照が無効です')).toBeVisible()
})

test('MCを作成し、無効なMCを再有効化できる', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 })
  await page.goto('/admin/mcs')
  await page.getByRole('button', { name: 'MCを追加' }).click()
  const dialog = page.getByRole('dialog')
  const inputs = dialog.locator('input[type="text"]')
  await inputs.nth(0).fill('mc-new')
  await inputs.nth(1).fill('新規MC')
  await inputs.nth(2).fill('サブMC')
  await dialog.getByRole('button', { name: '追加する' }).click()
  await expect(page.getByText('mc-new')).toBeVisible()
  await expect(page.getByText('新規MC')).toBeVisible()

  await page.getByLabel('無効なMCも表示する').check()
  const inactiveRow = page.getByRole('row').filter({ hasText: 'mc-inactive' })
  await expect(inactiveRow).toBeVisible()
  await inactiveRow.getByRole('button', { name: '編集' }).click()
  const editDialog = page.getByRole('dialog')
  await editDialog.getByRole('switch').click()
  await expect(editDialog.getByRole('switch')).toHaveAttribute('aria-checked', 'true')
  await editDialog.getByRole('button', { name: '保存する' }).click()
  await expect(page.getByRole('row').filter({ hasText: 'mc-inactive' }).getByText('有効')).toBeVisible()
  const state = await readMockState(page)
  expect(
    state.mutations.some(
      (mutation) => mutation.method === 'PUT' && mutation.resource === 'mc' && mutation.body.is_active === true,
    ),
  ).toBeTruthy()
})
