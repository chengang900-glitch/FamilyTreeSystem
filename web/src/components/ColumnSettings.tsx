import { useState } from 'react'
import { Button, Dropdown } from 'antd'

export interface ColumnMeta {
  key: string
  title: React.ReactNode
}

export function useColumnSettings<T extends { key: string }>(storageKey: string) {
  const [hidden, setHidden] = useState<string[]>(() => {
    try { return JSON.parse(localStorage.getItem(storageKey) || '[]') } catch { return [] }
  })
  const toggle = (key: string) => {
    const next = hidden.includes(key) ? hidden.filter((k) => k !== key) : [...hidden, key]
    setHidden(next)
    localStorage.setItem(storageKey, JSON.stringify(next))
  }
  const visible = (columns: T[]) => columns.filter((c) => !hidden.includes(c.key))
  return { hidden, toggle, visible }
}

export default function ColumnSettings(props: {
  columns: ColumnMeta[]
  hidden: string[]
  onToggle: (key: string) => void
}) {
  const { columns, hidden, onToggle } = props
  return (
    <Dropdown
      menu={{
        selectable: true,
        multiple: true,
        selectedKeys: columns.filter((c) => !hidden.includes(c.key)).map((c) => c.key),
        items: columns.map((c) => ({ key: c.key, label: c.title })),
        onClick: ({ key }) => onToggle(key),
      }}
    >
      <Button size="small">列设置</Button>
    </Dropdown>
  )
}
