import type { ScriptLine } from '../lib/api'

interface Props {
  lines: ScriptLine[]
}

const SECTION_LABEL: Record<string, string> = {
  intro: 'オープニング',
  news: 'ニュース',
  discussion: '注目トピック討論',
  outro: 'エンディング',
}

interface Section {
  section: string
  lines: ScriptLine[]
}

function groupBySection(lines: ScriptLine[]): Section[] {
  return lines.reduce<Section[]>((acc, line) => {
    const last = acc[acc.length - 1]
    if (!last || last.section !== line.section) {
      acc.push({ section: line.section, lines: [line] })
    } else {
      last.lines.push(line)
    }
    return acc
  }, [])
}

export default function ScriptViewer({ lines }: Props) {
  if (lines.length === 0) {
    return <p className="text-center text-gray-500 py-4">台本がありません</p>
  }

  const sections = groupBySection(lines)

  return (
    <div className="space-y-1">
      {sections.map((section, si) => (
        <div key={si}>
          <div className="text-center my-4">
            <span className="text-xs text-gray-400 bg-gray-100 px-3 py-1 rounded-full">
              {SECTION_LABEL[section.section] ?? section.section}
            </span>
          </div>
          <div className="space-y-3">
            {section.lines.map((line, li) => (
              <div
                key={li}
                className={`flex ${line.speaker === 'female' ? 'justify-end' : 'justify-start'}`}
              >
                <div
                  className={`max-w-[80%] rounded-2xl px-4 py-3 ${
                    line.speaker === 'male'
                      ? 'bg-blue-100 text-blue-900 rounded-tl-sm'
                      : 'bg-pink-100 text-pink-900 rounded-tr-sm'
                  }`}
                >
                  <p className="text-xs font-semibold mb-1 opacity-60">
                    {line.speaker === 'male' ? 'MC（男性）' : 'MC（女性）'}
                  </p>
                  <p className="text-sm leading-relaxed">{line.text}</p>
                </div>
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  )
}
