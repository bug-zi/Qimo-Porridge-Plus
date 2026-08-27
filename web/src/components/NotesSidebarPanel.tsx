import { useState } from 'react'
import { Eye, FileText } from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { glossaryMarkdownComponents } from '../glossary/termMatcher'

type NotesSidebarPanelProps = {
  note: string
  onNoteChange: (note: string) => void
}

export function NotesSidebarPanel({ note, onNoteChange }: NotesSidebarPanelProps) {
  const [isEditing, setIsEditing] = useState(false)

  return (
    <section className="right-notes-panel" aria-label="复习笔记">
      <section className="note-editor right-note-editor">
        <header>
          <div className="note-view-switch" role="group" aria-label="笔记显示方式">
            <button
              className={!isEditing ? 'is-active' : ''}
              type="button"
              onClick={() => setIsEditing(false)}
            >
              <Eye size={14} /> 预览
            </button>
            <button
              className={isEditing ? 'is-active' : ''}
              type="button"
              onClick={() => setIsEditing(true)}
            >
              <FileText size={14} /> 编辑
            </button>
          </div>
        </header>
        {isEditing ? (
          <textarea
            aria-label="编辑 Markdown 笔记"
            value={note}
            onChange={(event) => onNoteChange(event.target.value)}
          />
        ) : (
          <article className="note-markdown-preview">
            {note.trim() ? (
              <ReactMarkdown remarkPlugins={[remarkGfm]} components={glossaryMarkdownComponents()}>{note}</ReactMarkdown>
            ) : (
              <p className="note-empty">还没有笔记内容</p>
            )}
          </article>
        )}
      </section>
    </section>
  )
}
