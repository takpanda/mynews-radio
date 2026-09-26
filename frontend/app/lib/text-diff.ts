export type DiffLine = { type: 'same' | 'added' | 'removed'; text: string }

const MAX_LCS_CELLS = 4_000_000

/** oldTextからnewTextへの行単位の差分。追加はnewText側、削除はoldText側の行として返す。 */
export function diffLines(oldText: string, newText: string): DiffLine[] {
  const a = oldText.split('\n')
  const b = newText.split('\n')
  const n = a.length
  const m = b.length

  if (n * m > MAX_LCS_CELLS) {
    return diffLinesFallback(a, b)
  }

  const dp: number[][] = Array.from({ length: n + 1 }, () => new Array<number>(m + 1).fill(0))
  for (let i = n - 1; i >= 0; i -= 1) {
    for (let j = m - 1; j >= 0; j -= 1) {
      dp[i][j] = a[i] === b[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1])
    }
  }

  const result: DiffLine[] = []
  let i = 0
  let j = 0
  while (i < n && j < m) {
    if (a[i] === b[j]) {
      result.push({ type: 'same', text: a[i] })
      i += 1
      j += 1
    } else if (dp[i + 1][j] >= dp[i][j + 1]) {
      result.push({ type: 'removed', text: a[i] })
      i += 1
    } else {
      result.push({ type: 'added', text: b[j] })
      j += 1
    }
  }
  while (i < n) {
    result.push({ type: 'removed', text: a[i] })
    i += 1
  }
  while (j < m) {
    result.push({ type: 'added', text: b[j] })
    j += 1
  }
  return result
}

/** 入力が大きすぎてLCSが現実的でない場合の簡易フォールバック。同じ位置の行だけ一致とみなす。 */
function diffLinesFallback(a: string[], b: string[]): DiffLine[] {
  const result: DiffLine[] = []
  const max = Math.max(a.length, b.length)
  for (let i = 0; i < max; i += 1) {
    if (i < a.length && i < b.length && a[i] === b[i]) {
      result.push({ type: 'same', text: a[i] })
      continue
    }
    if (i < a.length) result.push({ type: 'removed', text: a[i] })
    if (i < b.length) result.push({ type: 'added', text: b[i] })
  }
  return result
}
