import { useEffect, useRef, useState } from 'react'
import { DatePicker, Input, Select, Space } from 'antd'
import dayjs from 'dayjs'
import customParseFormat from 'dayjs/plugin/customParseFormat'
import 'dayjs/locale/zh-cn'

dayjs.extend(customParseFormat)
dayjs.locale('zh-cn')
type Mode = 'day' | 'month' | 'year' | 'text'
function modeOf(value?: string | null): Mode {
  if (!value) return 'day'
  if (/^\d{4}-\d{2}-\d{2}$/.test(value)) return dayjs(value, 'YYYY-MM-DD', true).isValid() ? 'day' : 'text'
  if (/^\d{4}-\d{2}$/.test(value)) return 'month'
  if (/^\d{4}$/.test(value)) return 'year'
  return 'text'
}

/** 保留原始农历文字；仅知年份时不补出虚假的月日。 */
export default function DateInput({ id, value, onChange, disabled }: {
  id?: string; value?: string | null; onChange?: (v: string | null) => void; disabled?: boolean
}) {
  const [mode, setMode] = useState<Mode>(() => modeOf(value))
  const emitted = useRef(value)
  const emit = (next: string | null) => { emitted.current = next; onChange?.(next) }
  useEffect(() => { if (value !== emitted.current) setMode(modeOf(value)) }, [value])
  const format = mode === 'year' ? 'YYYY' : mode === 'month' ? 'YYYY-MM' : 'YYYY-MM-DD'
  const parsed = value && mode !== 'text' ? dayjs(value, format, true) : null
  return <Space.Compact style={{ width: '100%' }}>
    <Select aria-label="日期精度" value={mode} style={{ width: 110 }} disabled={disabled}
      onChange={setMode} options={[{ value: 'day', label: '公历日期' }, { value: 'month', label: '仅知年月' },
        { value: 'year', label: '仅知年份' }, { value: 'text', label: '农历/文字' }]} />
    {mode === 'text' ? <Input id={id} value={value || ''} disabled={disabled}
      placeholder="如：乙卯年正月廿七；保留原文" onChange={e => emit(e.target.value || null)} /> :
      <DatePicker id={id} value={parsed?.isValid() ? parsed : null} disabled={disabled}
        style={{ flex: 1, minWidth: 120 }} picker={mode === 'day' ? 'date' : mode} format={format}
        placeholder={value && !parsed?.isValid() ? `原值：${value}，请选择` : '选择公历日期'}
        onChange={v => emit(v ? v.format(format) : null)} />}
  </Space.Compact>
}
