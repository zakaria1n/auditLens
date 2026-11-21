import type { ReactNode } from 'react'

import { VizBlock } from '../features/intelligent-ui/VizBlock'
import type { VizCallbacks } from '../features/intelligent-ui/renderers'
import { CopyButton } from './ui/CopyButton'

/**
 * Rendu markdown léger (aucune dépendance) : titres, gras, italique, code
 * inline, blocs de code, listes, séparateurs. Le rapport du backend reste
 * téléchargeable en .md pour un rendu complet.
 *
 * Canal Generative UI (Phase 3) : un bloc ```viz contenant une spécification
 * JSON conforme au registre (version, type allowlisté, données bornées,
 * preuves référencées) est VALIDÉ puis rendu par les composants approuvés.
 * Une spécification invalide est rendue comme message de repli — jamais exécutée.
 */

export interface MarkdownViewProps {
  markdown: string
  vizCallbacks?: VizCallbacks
  isStreaming?: boolean
}

function renderInline(text: string, keyPrefix: string): ReactNode[] {
  const nodes: ReactNode[] = []
  const pattern = /(\*\*[^*]+\*\*|\*[^*]+\*|`[^`]+`)/g
  let last = 0
  let match: RegExpExecArray | null
  let i = 0
  while ((match = pattern.exec(text)) !== null) {
    if (match.index > last) nodes.push(text.slice(last, match.index))
    const token = match[0]
    const key = `${keyPrefix}-i${i++}`
    if (token.startsWith('**')) {
      nodes.push(
        <strong key={key} className="font-semibold text-slate-900">
          {token.slice(2, -2)}
        </strong>,
      )
    } else if (token.startsWith('`')) {
      nodes.push(
        <code key={key} className="rounded bg-slate-100 px-1 py-0.5 font-mono text-xs text-slate-800">
          {token.slice(1, -1)}
        </code>,
      )
    } else {
      nodes.push(<em key={key}>{token.slice(1, -1)}</em>)
    }
    last = match.index + token.length
  }
  if (last < text.length) nodes.push(text.slice(last))
  return nodes
}

export function MarkdownView({ markdown, vizCallbacks, isStreaming = false }: MarkdownViewProps) {
  const lines = markdown.split('\n')
  const blocks: ReactNode[] = []
  let i = 0
  let key = 0

  while (i < lines.length) {
    const line = lines[i]

    // Bloc de code — canal viz si le fence est `viz`
    if (line.trimStart().startsWith('```')) {
      const fence = line.trimStart().slice(3).trim().toLowerCase()
      const codeLines: string[] = []
      i += 1
      while (i < lines.length && !lines[i].trimStart().startsWith('```')) {
        codeLines.push(lines[i])
        i += 1
      }
      const closed = i < lines.length
      i += 1 // fermant
      if (fence === 'viz') {
        if (!closed && isStreaming) {
          blocks.push(<div key={`b${key++}`} role="status" className="my-3 rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-500">Préparation de la présentation…</div>)
          continue
        }
        let raw: unknown = null
        try {
          raw = JSON.parse(codeLines.join('\n'))
        } catch {
          blocks.push(<div key={`b${key++}`} className="my-2 rounded-xl border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800">
            <p>Cette présentation n’a pas pu être affichée. La réponse textuelle reste disponible.</p>
            <details><summary>Détails techniques</summary><p>Le bloc de présentation ne contient pas de JSON complet et valide. Les données n’ont pas été réparées automatiquement.</p></details>
          </div>)
          continue
        }
        blocks.push(<VizBlock key={`b${key++}`} raw={raw} callbacks={vizCallbacks} />)
        continue
      }
      const code = codeLines.join('\n')
      blocks.push(
        <div key={`b${key++}`} className="my-3 min-w-0 overflow-hidden rounded-xl bg-slate-900">
          <div className="flex items-center justify-between border-b border-white/10 px-4 py-2 text-xs text-slate-300">
            <span>{fence || 'Code'}</span><CopyButton text={code} label="Copier le code" className="text-slate-300 hover:text-white" />
          </div>
          <pre className="overflow-x-auto p-4 font-mono text-xs leading-relaxed text-slate-100"><code>{code}</code></pre>
        </div>,
      )
      continue
    }

    // GFM tables are common in audit answers. Keep the table scrollable on mobile.
    if (line.includes('|') && i + 1 < lines.length && /^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?\s*$/.test(lines[i + 1])) {
      const cells = (row: string) => row.trim().replace(/^\||\|$/g, '').split('|').map(cell => cell.trim())
      const headers = cells(line)
      const rows: string[][] = []
      i += 2
      while (i < lines.length && lines[i].includes('|') && lines[i].trim()) rows.push(cells(lines[i++]))
      blocks.push(<div key={`b${key++}`} className="my-3 max-w-full overflow-x-auto rounded-lg border border-slate-200">
        <table className="w-full min-w-max border-collapse text-left text-sm">
          <thead className="bg-slate-50"><tr>{headers.map((cell, index) => <th key={index} scope="col" className="px-3 py-2 font-semibold">{renderInline(cell, `th${key}-${index}`)}</th>)}</tr></thead>
          <tbody>{rows.map((row, ri) => <tr key={ri} className="border-t border-slate-100">{headers.map((_, ci) => <td key={ci} className="px-3 py-2 align-top">{renderInline(row[ci] ?? '', `td${key}-${ri}-${ci}`)}</td>)}</tr>)}</tbody>
        </table>
      </div>)
      continue
    }

    // Titres
    const heading = /^(#{1,6})\s+(.*)$/.exec(line)
    if (heading) {
      const level = heading[1].length
      const cls =
        level === 1
          ? 'text-lg font-semibold text-slate-900 mt-4'
          : level === 2
            ? 'text-base font-semibold text-slate-900 mt-4'
            : 'text-sm font-semibold text-slate-800 mt-3'
      // vraies balises h1..h6 : la structure de titres reste lisible par les lecteurs d'écran
      const Tag = (`h${level}` as 'h1' | 'h2' | 'h3' | 'h4' | 'h5' | 'h6')
      blocks.push(
        <Tag key={`b${key++}`} className={cls}>
          {renderInline(heading[2], `h${key}`)}
        </Tag>,
      )
      i += 1
      continue
    }

    // Séparateur
    if (/^(-{3,}|\*{3,})\s*$/.test(line.trim())) {
      blocks.push(<hr key={`b${key++}`} className="my-4 border-slate-200" />)
      i += 1
      continue
    }

    // Listes à puces / numérotées
    const bullet = /^\s*[-*]\s+(.*)$/.exec(line)
    const ordered = /^\s*\d+[.)]\s+(.*)$/.exec(line)
    if (bullet || ordered) {
      const isOrdered = ordered != null
      const items: string[] = []
      while (i < lines.length) {
        const m = isOrdered
          ? /^\s*\d+[.)]\s+(.*)$/.exec(lines[i])
          : /^\s*[-*]\s+(.*)$/.exec(lines[i])
        if (m) {
          items.push(m[1])
          i += 1
        } else {
          break
        }
      }
      const ListTag = isOrdered ? 'ol' : 'ul'
      blocks.push(
        <ListTag
          key={`b${key++}`}
          className={`my-2 space-y-1 pl-5 text-sm text-slate-700 ${
            isOrdered ? 'list-decimal' : 'list-disc'
          }`}
        >
          {items.map((item, idx) => (
            <li key={idx}>{renderInline(item, `li${key}-${idx}`)}</li>
          ))}
        </ListTag>,
      )
      continue
    }

    // Ligne vide
    if (line.trim() === '') {
      i += 1
      continue
    }

    // Paragraphe (fusionne les lignes consécutives non vides)
    const para: string[] = []
    while (i < lines.length && lines[i].trim() !== '' && !/^(#{1,6})\s/.test(lines[i]) && !/^\s*[-*]\s/.test(lines[i]) && !/^\s*\d+[.)]\s/.test(lines[i]) && !lines[i].trimStart().startsWith('```')) {
      para.push(lines[i])
      i += 1
    }
    blocks.push(
      <p key={`b${key++}`} className="my-2 text-sm leading-relaxed text-slate-700">
        {renderInline(para.join(' '), `p${key}`)}
      </p>,
    )
  }

  return <div className="flex min-w-0 flex-col break-words" dir="auto">{blocks}</div>
}
