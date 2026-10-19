import { useEffect, useRef, useState } from 'react'
import { Select, Spin, message } from 'antd'
import { api } from '../api'
import { useStore } from '../store'

export default function EntitySelect({ id, entityType, value, onChange }: {
  id?: string; entityType?: string; value?: number; onChange?: (value?: number) => void
}) {
  const { familyId } = useStore()
  const [options, setOptions] = useState<{ value: number; label: string }[]>([])
  const [keyword, setKeyword] = useState('')
  const [page, setPage] = useState(1)
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(false)
  const serial = useRef(0)
  useEffect(() => {
    setOptions([]); setKeyword(''); setPage(1); setTotal(0)
  }, [familyId, entityType])
  useEffect(() => {
    const request = ++serial.current
    if (!familyId || !entityType) return
    setLoading(true)
    const timer = window.setTimeout(async () => {
      const qs = new URLSearchParams({ entity_type: entityType, keyword, page: String(page), size: '30' })
      try {
        const d = await api.get(`/api/families/${familyId}/relation-targets?${qs}`)
        if (serial.current !== request) return
        const next = d.items.map((r: any) => ({ value: r.id, label: r.label }))
        setOptions(prev => page === 1 ? next : [...prev, ...next.filter((r: any) => !prev.some(p => p.value === r.value))])
        setTotal(d.total)
      } catch (e: any) {
        if (serial.current === request) message.error(e.message)
      } finally {
        if (serial.current === request) setLoading(false)
      }
    }, 250)
    return () => { window.clearTimeout(timer); serial.current++ }
  }, [familyId, entityType, keyword, page])
  return <Select id={id} showSearch allowClear disabled={!entityType} placeholder="搜索姓名或名称"
    value={value} onChange={onChange} filterOption={false} options={options} loading={loading}
    notFoundContent={loading ? <Spin size="small" /> : '没有匹配对象'}
    onSearch={v => { serial.current++; setKeyword(v); setPage(1) }}
    onPopupScroll={e => {
      const box = e.currentTarget
      if (!loading && options.length < total && box.scrollTop + box.clientHeight >= box.scrollHeight - 24) setPage(p => p + 1)
    }} />
}
