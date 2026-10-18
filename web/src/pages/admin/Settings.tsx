import { useEffect, useState } from 'react'
import { Button, Card, Input, InputNumber, Space, Switch, Tabs, Typography, message } from 'antd'
import { api } from '../../api'

interface Item {
  key: string
  value: any
  type: string
  group_name: string
  label: string
  description: string
}

const GROUPS: Record<string, string> = {
  access: '访问与隐私',
  security: '安全',
  site: '站点',
  storage: '存储与备份',
}

export default function Settings() {
  const [items, setItems] = useState<Item[]>([])
  const [draft, setDraft] = useState<Record<string, any>>({})

  useEffect(() => {
    api.get<Item[]>('/api/admin/settings').then(setItems).catch((e) => message.error(e.message))
  }, [])

  const save = async () => {
    try {
      await api.put('/api/admin/settings', draft)
      message.success('设置已保存')
      setDraft({})
      setItems(await api.get('/api/admin/settings'))
    } catch (e: any) {
      message.error(e.message)
    }
  }

  const renderControl = (it: Item) => {
    const value = draft[it.key] !== undefined ? draft[it.key] : it.value
    const set = (v: any) => setDraft({ ...draft, [it.key]: v })
    if (it.type === 'bool') return <Switch checked={!!value} onChange={set} />
    if (it.type === 'int') return <InputNumber value={value} onChange={set} style={{ width: 160 }} />
    return <Input value={value ?? ''} onChange={(e) => set(e.target.value)} style={{ width: 320 }} />
  }

  const groups = Object.keys(GROUPS).filter((g) => items.some((i) => i.group_name === g))

  return (
    <Card
      title="系统设置"
      extra={
        <Space>
          <Button onClick={() => setDraft({})}>撤销更改</Button>
          <Button type="primary" onClick={save} disabled={!Object.keys(draft).length}>
            保存
          </Button>
        </Space>
      }
    >
      <Tabs
        items={groups.map((g) => ({
          key: g,
          label: GROUPS[g],
          children: (
            <div>
              {items
                .filter((i) => i.group_name === g)
                .map((it) => (
                  <div
                    key={it.key}
                    style={{
                      display: 'flex', flexWrap: 'wrap', gap: 8, alignItems: 'center',
                      padding: '10px 0', borderBottom: '1px solid #f5f5f5',
                    }}
                  >
                    <div style={{ minWidth: 220 }}>
                      <Typography.Text strong>{it.label}</Typography.Text>
                      <div style={{ fontSize: 12, color: '#999' }}>{it.key}</div>
                    </div>
                    <div style={{ flex: 1, minWidth: 200 }}>{renderControl(it)}</div>
                    <div style={{ fontSize: 12, color: '#888', minWidth: 200 }}>
                      {it.description}
                    </div>
                  </div>
                ))}
            </div>
          ),
        }))}
      />
    </Card>
  )
}
