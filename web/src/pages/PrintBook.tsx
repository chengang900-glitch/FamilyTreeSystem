import { useEffect, useState } from 'react'
import {
  Alert, Button, Card, Radio, Select, Space, Steps, Tag, Input, message,
} from 'antd'
import { PrinterOutlined } from '@ant-design/icons'
import { api } from '../api'
import { useStore } from '../store'

export default function PrintBook() {
  const { familyId } = useStore()
  const [step, setStep] = useState(0)
  const [people, setPeople] = useState<any[]>([])
  const [mode, setMode] = useState<'lineage' | 'person'>('lineage')
  const [rootId, setRootId] = useState<number | undefined>()
  const [generations, setGenerations] = useState(-1)
  const [includeSpouse, setIncludeSpouse] = useState(true)
  const [includeChildren, setIncludeChildren] = useState(true)
  const [addCover, setAddCover] = useState(true)
  const [compiler, setCompiler] = useState('')
  const [paper, setPaper] = useState('A4')
  const [fmt, setFmt] = useState<'pdf' | 'docx'>('pdf')
  const [est, setEst] = useState<any>(null)

  useEffect(() => {
    if (!familyId) return
    api.get(`/api/families/${familyId}/persons?size=500`).then((d) => {
      setPeople(d.items)
      if (d.items.length) setRootId(d.items[0].id)
    }).catch(() => {})
    api.get(`/api/families/${familyId}`).then((f) => setCompiler(f.compiler || '')).catch(() => {})
  }, [familyId])

  const estimate = async () => {
    try {
      setEst(await api.post(`/api/families/${familyId}/print/estimate`, {
        mode, root_id: rootId, generations, add_cover: addCover, paper,
      }))
    } catch (e: any) {
      message.error(e.message)
    }
  }

  useEffect(() => {
    if (step === 1) estimate()
  }, [step, mode, rootId, generations, addCover, paper])

  const download = async () => {
    const payload = {
      mode, root_id: rootId, generations, include_spouse: includeSpouse,
      include_children: includeChildren, add_cover: addCover, compiler, paper,
    }
    try {
      const res = await fetch(`/api/families/${familyId}/print/${fmt}`, {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'fetch' },
        body: JSON.stringify(payload),
      })
      if (!res.ok) {
        const j = await res.json().catch(() => null)
        throw new Error(j?.msg || '导出失败')
      }
      const blob = await res.blob()
      const a = document.createElement('a')
      a.href = URL.createObjectURL(blob)
      a.download = `族谱.${fmt === 'pdf' ? 'pdf' : 'docx'}`
      a.click()
    } catch (e: any) {
      message.error(e.message)
    }
  }

  return (
    <Card title="族谱付印">
      <Steps
        current={step}
        size="small"
        style={{ marginBottom: 20 }}
        items={[{ title: '主人物与模式' }, { title: '导出内容' }, { title: '纸张与格式' }]}
      />

      {step === 0 && (
        <Space direction="vertical" size={16} style={{ width: '100%' }}>
          <Space wrap>
            <span>导出模式</span>
            <Radio.Group
              value={mode}
              onChange={(e) => setMode(e.target.value)}
              optionType="button"
              options={[
                { value: 'lineage', label: '世系（整谱）' },
                { value: 'person', label: '个人（某人及其后代）' },
              ]}
            />
          </Space>
          {mode === 'person' && (
            <Space wrap>
              <span>主人物</span>
              <Select
                showSearch
                optionFilterProp="label"
                style={{ width: 240 }}
                value={rootId}
                onChange={setRootId}
                options={people.map((p) => ({
                  value: p.id, label: `第${p.generation}世 ${p.name}`,
                }))}
              />
            </Space>
          )}
        </Space>
      )}

      {step === 1 && (
        <Space direction="vertical" size={16} style={{ width: '100%' }}>
          <Space wrap>
            <span>世代深度</span>
            <Select
              style={{ width: 160 }}
              value={generations}
              onChange={setGenerations}
              options={[
                { value: -1, label: '全部世代' },
                { value: 3, label: '3 代' },
                { value: 4, label: '4 代' },
                { value: 5, label: '5 代' },
              ]}
            />
          </Space>
          <Space wrap>
            <label>
              <input type="checkbox" checked={includeSpouse}
                onChange={(e) => setIncludeSpouse(e.target.checked)} /> 含配偶详细信息
            </label>
            <label>
              <input type="checkbox" checked={includeChildren}
                onChange={(e) => setIncludeChildren(e.target.checked)} /> 含子女姓名列表
            </label>
            <label>
              <input type="checkbox" checked={addCover}
                onChange={(e) => setAddCover(e.target.checked)} /> 加封面
            </label>
          </Space>
          <Space wrap>
            <span>修辑者署名</span>
            <Input
              style={{ width: 200 }}
              value={compiler}
              onChange={(e) => setCompiler(e.target.value)}
              placeholder="如：张三 敬修"
            />
          </Space>
          {est && (
            <Alert
              type="info"
              showIcon
              message={`核心成员 ${est.persons} 人，预估 ${est.pages} 页（${paper}）`}
            />
          )}
        </Space>
      )}

      {step === 2 && (
        <Space direction="vertical" size={16} style={{ width: '100%' }}>
          <Space wrap>
            <span>纸张规格</span>
            <Select
              style={{ width: 160 }}
              value={paper}
              onChange={setPaper}
              options={[
                { value: 'A4', label: 'A4（210×297mm）' },
                { value: 'A5', label: 'A5（148×210mm）' },
                { value: '16K', label: '16 开（195×270mm）' },
                { value: '32K', label: '32 开（130×184mm）' },
              ]}
            />
          </Space>
          <Space wrap>
            <span>导出格式</span>
            <Radio.Group
              value={fmt}
              onChange={(e) => setFmt(e.target.value)}
              optionType="button"
              options={[
                { value: 'pdf', label: 'PDF（可直接送印）' },
                { value: 'docx', label: 'Word（可继续编辑）' },
              ]}
            />
          </Space>
          <Tag color="blue">中文字体由服务器自动选择（思源/雅黑/宋体）</Tag>
        </Space>
      )}

      <div style={{ marginTop: 24 }}>
        <Space>
          {step > 0 && <Button onClick={() => setStep(step - 1)}>上一步</Button>}
          {step < 2 && <Button type="primary" onClick={() => setStep(step + 1)}>下一步</Button>}
          {step === 2 && (
            <Button type="primary" icon={<PrinterOutlined />} onClick={download}>
              导出{fmt === 'pdf' ? 'PDF' : 'Word'}
            </Button>
          )}
        </Space>
      </div>
    </Card>
  )
}
