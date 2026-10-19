import { appUrl } from '../url'
import { useEffect, useRef, useState } from 'react'
import {
  Alert, Button, Card, Radio, Select, Space, Steps, Tag, Input, Modal, message,
} from 'antd'
import { PrinterOutlined } from '@ant-design/icons'
import { api } from '../api'
import { useStore } from '../store'
import PersonSelect from '../components/PersonSelect'
import PdfPreview from '../components/PdfPreview'

const TEMPLATES = [
  { value: 'original', label: '原版', description: 'PDF 双栏；Word 人物表格' },
  { value: 'traditional', label: '传统竖排分栏式', description: '分世横栏、竖排正文、右侧谱名堂号' },
  { value: 'european', label: '横行体', description: '五世分格，世次从右向左，人名附传' },
  { value: 'compilation', label: '汇编体', description: '按世代逐人编排，单栏人物条目' },
]

export default function PrintBook() {
  const { familyId } = useStore()
  const [step, setStep] = useState(0)
  const [mode, setMode] = useState<'lineage' | 'person'>('lineage')
  const [rootId, setRootId] = useState<number | undefined>()
  const [generations, setGenerations] = useState(-1)
  const [includeSpouse, setIncludeSpouse] = useState(true)
  const [includeChildren, setIncludeChildren] = useState(true)
  const [addCover, setAddCover] = useState(true)
  const [compiler, setCompiler] = useState('')
  const [paper, setPaper] = useState('A4')
  const [template, setTemplate] = useState('original')
  const [preview, setPreview] = useState<{ url: string; blob: Blob } | null>(null)
  const [previewOpen, setPreviewOpen] = useState(false)
  const [previewing, setPreviewing] = useState(false)
  const previewSerial = useRef(0)
  const wordAllowed = template === 'original' || template === 'compilation'
  const templateLabel = TEMPLATES.find(t => t.value === template)!.label
  const [fmt, setFmt] = useState<'pdf' | 'docx'>('pdf')
  const [est, setEst] = useState<any>(null)
  const [exporting, setExporting] = useState(false)
  const estimateSerial = useRef(0)

  useEffect(() => {
    let active = true
    setRootId(undefined)
    setCompiler('')
    if (!familyId) return
    api.get(`/api/families/${familyId}/persons?size=1`).then((d) => {
      if (active && d.items.length) setRootId(d.items[0].id)
    }).catch(() => {})
    api.get(`/api/families/${familyId}`).then((f) => { if (active) setCompiler(f.compiler || '') }).catch(() => {})
    return () => { active = false }
  }, [familyId])

  const estimate = async (serial: number) => {
    try {
      const result = await api.post(`/api/families/${familyId}/print/estimate`, {
        mode, root_id: rootId, generations, add_cover: addCover, paper,
        include_spouse: includeSpouse, include_children: includeChildren, compiler, template,
      })
      if (estimateSerial.current === serial) setEst(result)
    } catch (e: any) {
      if (estimateSerial.current === serial) message.error(e.message)
    }
  }

  useEffect(() => {
    const serial = ++estimateSerial.current
    setEst(null)
    if (step === 0 || !familyId || (mode === 'person' && !rootId)) return
    const timer = window.setTimeout(() => estimate(serial), 300)
    return () => { window.clearTimeout(timer); estimateSerial.current++ }
  }, [step, familyId, mode, rootId, generations, addCover, paper, includeSpouse, includeChildren, compiler, template])

  useEffect(() => {
    previewSerial.current++
    setPreview(null); setPreviewOpen(false); setPreviewing(false)
  }, [familyId, mode, rootId, generations, includeSpouse, includeChildren, addCover, compiler, paper, template])
  useEffect(() => () => { if (preview) URL.revokeObjectURL(preview.url) }, [preview])
  useEffect(() => () => { previewSerial.current++ }, [])

  const requestFile = async (format: 'pdf' | 'docx') => {
    const res = await fetch(appUrl(`/api/families/${familyId}/print/${format}`), {
      method: 'POST', credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'fetch' },
      body: JSON.stringify({ mode, root_id: rootId, generations, include_spouse: includeSpouse,
        include_children: includeChildren, add_cover: addCover, compiler, paper, template }),
    })
    if (!res.ok) {
      const j = await res.json().catch(() => null)
      throw new Error(j?.msg || '导出失败')
    }
    return res.blob()
  }

  const showPreview = async () => {
    if (mode === 'person' && !rootId) { message.warning('请选择主人物'); return }
    const serial = ++previewSerial.current
    setPreviewing(true)
    try {
      const blob = await requestFile('pdf')
      if (serial !== previewSerial.current) return
      setPreview({ url: URL.createObjectURL(blob), blob }); setPreviewOpen(true)
    } catch (e: any) {
      if (serial === previewSerial.current) message.error(e.message)
    } finally {
      if (serial === previewSerial.current) setPreviewing(false)
    }
  }

  const download = async () => {
    if (mode === 'person' && !rootId) { message.warning('请选择主人物'); return }
    setExporting(true)
    try {
      const cached = fmt === 'pdf' && preview?.url
      const url = cached || URL.createObjectURL(await requestFile(fmt))
      const a = document.createElement('a')
      a.href = url; a.download = `族谱_${templateLabel}.${fmt}`; a.click()
      if (!cached) setTimeout(() => URL.revokeObjectURL(url), 1000)
    } catch (e: any) {
      message.error(e.message)
    } finally {
      setExporting(false)
    }
  }

  return (
    <Card title="族谱付印">
      <p style={{ color: '#666' }}>付印范围不包含“其他（男）”和“其他（女）”。</p>
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
          <Space direction="vertical" size={8} style={{ width: '100%' }}>
            <span>付印模板</span>
            <Radio.Group aria-label="付印模板" value={template} onChange={e => {
              setTemplate(e.target.value)
              if (['traditional', 'european'].includes(e.target.value)) setFmt('pdf')
            }}>
              <Space wrap>
                {TEMPLATES.map(t => <Radio.Button key={t.value} value={t.value}>{t.label}</Radio.Button>)}
              </Space>
            </Radio.Group>
            <span style={{ color: '#666' }}>{TEMPLATES.find(t => t.value === template)!.description}</span>
          </Space>
          {mode === 'person' && (
            <Space wrap>
              <span>主人物</span>
              <PersonSelect
                allowedTypes={[1, 2, 3, 4, 5, 6]}
                style={{ width: 240 }}
                value={rootId}
                onChange={setRootId}
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
              aria-label="世代深度"
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
              aria-label="修辑者署名"
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
              message={`核心成员 ${est.persons} 人，PDF 预估 ${est.pages} 页（${paper}）；Word 页数由编辑器排版决定`}
            />
          )}
        </Space>
      )}

      {step === 2 && (
        <Space direction="vertical" size={16} style={{ width: '100%' }}>
          <Space wrap>
            <span>纸张规格</span>
            <Select
              aria-label="纸张规格"
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
                { value: 'docx', label: 'Word（可继续编辑）', disabled: !wordAllowed },
              ]}
            />
          </Space>
          <Tag color="blue" style={{ whiteSpace: 'normal' }}>{templateLabel}：{TEMPLATES.find(t => t.value === template)!.description}</Tag>
          {!wordAllowed && <span>此模板提供 PDF 预览和导出；需要可编辑 Word 时请选择原版或汇编体。</span>}
          {preview && <Tag color="green">PDF 导出与本次预览文件一致</Tag>}
          {est && <Tag>核心成员 {est.persons} 人，PDF 预估 {est.pages} 页</Tag>}
        </Space>
      )}

      <div style={{ marginTop: 24 }}>
        <Space wrap>
          {step > 0 && <Button onClick={() => setStep(step - 1)}>上一步</Button>}
          {step < 2 && <Button type="primary" disabled={mode === 'person' && !rootId} onClick={() => setStep(step + 1)}>下一步</Button>}
          {step === 2 && <Button loading={previewing} disabled={exporting} onClick={showPreview}>预览PDF</Button>}
          {step === 2 && (
            <Button type="primary" loading={exporting} icon={<PrinterOutlined />} onClick={download}>
              导出{fmt === 'pdf' ? 'PDF' : 'Word'}
            </Button>
          )}
        </Space>
      </div>
      <Modal title={`${templateLabel} · PDF预览`} open={previewOpen} onCancel={() => setPreviewOpen(false)}
        width={1000} footer={<Space wrap>
          <Button onClick={() => setPreviewOpen(false)}>关闭预览</Button>
          <Button type="primary" loading={exporting} onClick={() => {
            if (!preview) return
            const a = document.createElement('a'); a.href = preview.url; a.download = `族谱_${templateLabel}.pdf`; a.click()
          }}>导出此PDF</Button>
        </Space>}>
        <p>预览为实际生成的 PDF，页数、纸张与下载文件一致。</p>
        {preview && <PdfPreview blob={preview.blob} />}
      </Modal>
    </Card>
  )
}
