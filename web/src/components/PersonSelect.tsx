import { useEffect, useRef, useState } from 'react'
import { Select, Spin } from 'antd'
import { api } from '../api'
import { useStore } from '../store'

interface PersonOption {
  id: number
  name: string
  generation: number
  courtesy_name?: string
  type: number
}

interface Props {
  id?: string
  excludeIds?: number[]
  allowedTypes?: number[]
  value?: number | number[]
  onChange?: (value: any) => void
  multiple?: boolean
  placeholder?: string
  style?: React.CSSProperties
  disabled?: boolean
}

function label(p: PersonOption) {
  return `第${p.generation}世 ${p.name}${p.courtesy_name ? `（${p.courtesy_name}）` : ''}`
}

/** 可远程搜索的成员选择器，避免一次性加载整谱导致大谱缺人。 */
export default function PersonSelect(props: Props) {
  const { familyId } = useStore()
  const [options, setOptions] = useState<PersonOption[]>([])
  const [loading, setLoading] = useState(false)
  const timer = useRef<number | undefined>(undefined)
  const requested = useRef<Set<number>>(new Set())
  const searchSerial = useRef(0)
  const typesKey = props.allowedTypes?.join(',') || ''

  const selectedIds = (Array.isArray(props.value) ? props.value : (props.value ? [props.value] : []))
    .map(Number)

  const load = async (keyword = '') => {
    if (!familyId) return
    const serial = ++searchSerial.current
    setLoading(true)
    try {
      const qs = `size=50${keyword ? `&keyword=${encodeURIComponent(keyword)}` : ''}${typesKey ? `&types=${encodeURIComponent(typesKey)}` : ''}`
      const data = await api.get(`/api/families/${familyId}/persons?${qs}`)
      const items: PersonOption[] = data.items || []
      if (serial !== searchSerial.current) return
      setOptions((prev) => {
        const keep = prev.filter((o) => selectedIds.includes(o.id) && !items.some((x) => x.id === o.id))
        return [...items, ...keep]
      })
    } catch {
      // 选择器搜索失败不打断表单，保留已有选项
    } finally {
      if (serial === searchSerial.current) setLoading(false)
    }
  }

  useEffect(() => {
    requested.current.clear()
    setOptions([])
    load('')
    return () => { window.clearTimeout(timer.current); searchSerial.current++ }
  }, [familyId, typesKey])

  // 编辑场景：当前值可能不在前 50 条里，单独取详情补标签
  useEffect(() => {
    if (!familyId) return
    selectedIds.forEach((id) => {
      if (options.some((o) => o.id === id) || requested.current.has(id)) return
      requested.current.add(id)
      api.get(`/api/families/${familyId}/persons/${id}`).then((p: PersonOption) => {
        setOptions((prev) => prev.some((o) => o.id === id) ? prev : [...prev, p])
      }).catch(() => {})
    })
  }, [familyId, selectedIds.join(','), options])

  const search = (keyword: string) => {
    searchSerial.current++
    window.clearTimeout(timer.current)
    timer.current = window.setTimeout(() => load(keyword), 300)
  }

  return (
    <Select
      id={props.id}
      showSearch
      allowClear
      filterOption={false}
      onSearch={search}
      loading={loading}
      notFoundContent={loading ? <Spin size="small" /> : undefined}
      mode={props.multiple ? 'multiple' : undefined}
      value={props.value}
      onChange={props.onChange}
      placeholder={props.placeholder || '搜索姓名/字/号'}
      style={props.style}
      disabled={props.disabled}
      options={options.filter(o => !props.excludeIds?.includes(o.id)
        && (!props.allowedTypes || props.allowedTypes.includes(o.type))).map((o) => ({ value: o.id, label: label(o) }))}
    />
  )
}
