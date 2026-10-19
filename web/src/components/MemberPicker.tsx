import { useEffect, useRef, useState } from 'react'
import { Button, Input, InputNumber, Select, Space, Table, Tag, message } from 'antd'
import { api } from '../api'
import { useStore } from '../store'
import { PERSON_TYPES } from '../constants'

/** 只选择当前页或明确勾选的成员；跨页保留选择，不暗中选择全库。 */
export default function MemberPicker({ value = [], onChange }: {
  value?: number[]; onChange?: (ids: number[]) => void
}) {
  const { familyId } = useStore()
  const [keyword, setKeyword] = useState('')
  const [generation, setGeneration] = useState<number | null>(null)
  const [type, setType] = useState<number>()
  const [page, setPage] = useState(1)
  const [rows, setRows] = useState<any[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(false)
  const serial = useRef(0)
  useEffect(() => {
    const request = ++serial.current
    setLoading(true)
    const timer = window.setTimeout(async () => {
      const qs = new URLSearchParams({ page: String(page), size: '20', keyword })
      if (generation) qs.set('generation', String(generation))
      if (type) qs.set('type', String(type))
      try {
        const d = await api.get(`/api/families/${familyId}/persons?${qs}`)
        if (serial.current !== request) return
        setRows(d.items)
        setTotal(d.total)
      } catch (e: any) {
        if (serial.current === request) message.error(e.message)
      } finally {
        if (serial.current === request) setLoading(false)
      }
    }, 200)
    return () => { window.clearTimeout(timer); serial.current++ }
  }, [familyId, keyword, generation, type, page])
  return <>
    <Space wrap style={{ marginBottom: 8 }}>
      <Input aria-label="筛选成员姓名" placeholder="姓名/字/号" style={{ width: 160 }} value={keyword}
        onChange={e => { setKeyword(e.target.value); setPage(1) }} allowClear />
      <InputNumber aria-label="筛选成员世代" placeholder="世代" min={1} max={999} value={generation}
        onChange={v => { setGeneration(v); setPage(1) }} />
      <Select aria-label="筛选成员类型" placeholder="类型" style={{ width: 110 }} value={type} allowClear
        onChange={v => { setType(v); setPage(1) }} options={Object.entries(PERSON_TYPES).map(([k, label]) => ({ value: +k, label }))} />
      <Tag>已选 {value.length} 人</Tag>
      <Button size="small" disabled={loading} onClick={() => onChange?.([...new Set([...value, ...rows.map(r => r.id)])])}>全选当前页</Button>
      <Button size="small" onClick={() => onChange?.([])}>取消全部选择</Button>
    </Space>
    <Table size="small" rowKey="id" dataSource={rows} loading={loading} scroll={{ x: 500 }}
      rowSelection={{ selectedRowKeys: value, preserveSelectedRowKeys: true, onChange: ids => onChange?.(ids.map(Number)) }}
      pagination={{ current: page, pageSize: 20, total, showSizeChanger: false, onChange: setPage }}
      columns={[{ title: '姓名', dataIndex: 'name' }, { title: '世代', dataIndex: 'generation' },
        { title: '类型', dataIndex: 'type', render: (t: number) => PERSON_TYPES[t] },
        { title: '所属分支', dataIndex: 'branch_name', render: (v: string) => v || '未分配' }]} />
  </>
}
