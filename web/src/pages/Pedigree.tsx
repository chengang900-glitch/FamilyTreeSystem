import { useEffect, useMemo, useRef, useState } from 'react'
import {
  Alert, Button, Card, Drawer, InputNumber, Select, Space, Switch, Tag, Tooltip, message,
} from 'antd'
import { DownloadOutlined, ZoomInOutlined, ZoomOutOutlined, CompressOutlined } from '@ant-design/icons'
import { api } from '../api'
import { useStore } from '../store'
import { PERSON_TYPES } from '../constants'
import { buildScene, middle, NODE_H, NODE_W } from '../pedigree/layout'
import type { PNode, Relations } from '../pedigree/layout'
import { pathOf } from '../pedigree/routing'

const LAYOUTS = [
  { value: 'tree', label: '树形图' }, { value: 'spine', label: '直系延展图' }, { value: 'side', label: '并排式' },
]

export default function Pedigree() {
  const { familyId } = useStore()
  const [nodes, setNodes] = useState<PNode[]>([])
  const [relations, setRelations] = useState<Relations>({})
  const [root, setRoot] = useState<number | null>(null)
  const [layout, setLayout] = useState('tree')
  const [orientation, setOrientation] = useState<'vertical' | 'horizontal'>('horizontal')
  const [directOnly, setDirectOnly] = useState(false)
  const [scale, setScale] = useState(1)
  const [exportMargin, setExportMargin] = useState(40)
  const [offset, setOffset] = useState({ x: 0, y: 0 })
  const [selected, setSelected] = useState<PNode | null>(null)
  const [viewport, setViewport] = useState({ width: 800, height: 500 })
  const svgRef = useRef<SVGSVGElement>(null)
  const canvasRef = useRef<HTMLDivElement>(null)
  const drag = useRef<{ x: number; y: number; ox: number; oy: number } | null>(null)
  const moved = useRef(false)
  const mobile = viewport.width < 768

  useEffect(() => {
    let active = true
    setNodes([]); setSelected(null); setRelations({})
    if (familyId) api.get(`/api/families/${familyId}/pedigree`).then(d => {
      if (active) { setNodes(d.nodes); setRelations({ marriages: d.marriages, parentchild: d.parentchild }); setRoot(d.root) }
    }).catch((e: any) => { if (active) message.error(e.message) })
    return () => { active = false }
  }, [familyId])

  const scene = useMemo(() => buildScene(layout, nodes, root as number, orientation, directOnly, relations),
    [layout, nodes, root, orientation, directOnly, relations])
  const bounds = scene.bounds
  // 图例也是导出内容；边界同时包含卡片和所有走线路径。
  const content = { ...bounds, maxX: Math.max(bounds.maxX, bounds.minX + 430), maxY: bounds.maxY + 44 }
  const width = content.maxX - content.minX, height = content.maxY - content.minY
  const fit = () => {
    const s = Math.max(.01, Math.min((viewport.width - 48) / width, (viewport.height - 48) / height, 1.2))
    setScale(s)
    setOffset({ x: (viewport.width - width * s) / 2 - content.minX * s, y: (viewport.height - height * s) / 2 - content.minY * s })
  }
  useEffect(() => {
    const box = canvasRef.current
    if (!box) return
    const observer = new ResizeObserver(() => setViewport({ width: box.clientWidth, height: box.clientHeight }))
    observer.observe(box)
    return () => observer.disconnect()
  }, [])
  useEffect(fit, [content.minX, content.minY, content.maxX, content.maxY, viewport.width, viewport.height, layout, orientation, directOnly])

  const zoom = (next: number, cx = viewport.width / 2, cy = viewport.height / 2) => {
    const s = Math.min(4, Math.max(.01, next)), ratio = s / scale
    setOffset({ x: cx - (cx - offset.x) * ratio, y: cy - (cy - offset.y) * ratio }); setScale(s)
  }
  const onWheel = (e: WheelEvent) => {
    e.preventDefault()
    const box = canvasRef.current!.getBoundingClientRect()
    zoom(scale * (e.deltaY > 0 ? .9 : 1.1), e.clientX - box.left, e.clientY - box.top)
  }
  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    canvas.addEventListener('wheel', onWheel, { passive: false })
    return () => canvas.removeEventListener('wheel', onWheel)
  }, [scale, offset.x, offset.y, viewport.width, viewport.height])
  const onPointerDown = (e: React.PointerEvent) => {
    moved.current = false; drag.current = { x: e.clientX, y: e.clientY, ox: offset.x, oy: offset.y }
    ;(e.target as Element).setPointerCapture?.(e.pointerId)
  }
  const onPointerMove = (e: React.PointerEvent) => {
    if (!drag.current) return
    const dx = e.clientX - drag.current.x, dy = e.clientY - drag.current.y
    if (Math.abs(dx) + Math.abs(dy) > 4) moved.current = true
    if (moved.current) setOffset({ x: drag.current.ox + dx, y: drag.current.oy + dy })
  }
  const pinch = useRef<{ dist: number; scale: number } | null>(null)
  const touchDist = (t: ArrayLike<{ clientX: number; clientY: number }>) => Math.hypot(t[0].clientX - t[1].clientX, t[0].clientY - t[1].clientY)
  const related = new Set(selected ? [selected.id, ...selected.parents, ...selected.children, ...selected.spouses] : [])

  const exportImage = async (fmt: 'png' | 'jpg' | 'svg') => {
    const svg = svgRef.current
    if (!svg || !scene.nodes.length) return
    const margin = Math.min(Math.max(exportMargin, 0), 200), clone = svg.cloneNode(true) as SVGSVGElement
    const ew = width + margin * 2, eh = height + margin * 2
    clone.setAttribute('width', String(ew)); clone.setAttribute('height', String(eh))
    clone.setAttribute('viewBox', `${content.minX - margin} ${content.minY - margin} ${ew} ${eh}`)
    clone.setAttribute('xmlns', 'http://www.w3.org/2000/svg')
    clone.querySelector('[data-scene]')?.removeAttribute('transform')
    clone.querySelectorAll('[data-edge], [data-person]').forEach(e => e.setAttribute('opacity', '1'))
    const bg = document.createElementNS('http://www.w3.org/2000/svg', 'rect')
    bg.setAttribute('x', String(content.minX - margin)); bg.setAttribute('y', String(content.minY - margin))
    bg.setAttribute('width', String(ew)); bg.setAttribute('height', String(eh)); bg.setAttribute('fill', '#fff'); clone.insertBefore(bg, clone.firstChild)
    const xml = new XMLSerializer().serializeToString(clone)
    const download = (url: string) => { const a = document.createElement('a'); a.href = url; a.download = `世系树_${layout}.${fmt}`; a.click() }
    const url = URL.createObjectURL(new Blob([xml], { type: 'image/svg+xml' }))
    if (fmt === 'svg') { download(url); setTimeout(() => URL.revokeObjectURL(url), 1000); return }
    const img = new Image()
    img.onload = () => {
      const canvas = document.createElement('canvas'), ratio = Math.min(2, 32760 / ew, 32760 / eh, Math.sqrt(64000000 / (ew * eh)))
      canvas.width = Math.max(1, Math.floor(ew * ratio)); canvas.height = Math.max(1, Math.floor(eh * ratio))
      const ctx = canvas.getContext('2d')!; ctx.fillStyle = '#fff'; ctx.fillRect(0, 0, canvas.width, canvas.height)
      ctx.drawImage(img, 0, 0, canvas.width, canvas.height); download(canvas.toDataURL(fmt === 'png' ? 'image/png' : 'image/jpeg', .95))
      if (ratio < 2) message.info('图幅较大，已按可用分辨率导出；无损放大请使用 SVG')
      URL.revokeObjectURL(url)
    }
    img.onerror = () => { URL.revokeObjectURL(url); message.error('图片导出失败，请重试或选择 SVG') }; img.src = url
  }

  return (
    <Card title="世系树" extra={<Space wrap>
      <Select aria-label="布局" size="small" style={{ width: 130 }} value={layout} onChange={setLayout} options={LAYOUTS} />
      <Select aria-label="方向" size="small" style={{ width: 100 }} value={layout === 'spine' ? 'horizontal' : orientation}
        disabled={!['tree', 'side'].includes(layout)} onChange={setOrientation}
        options={[{ value: 'vertical', label: '纵向' }, { value: 'horizontal', label: '横向' }]} />
      <Select aria-label="定位族人" size="small" showSearch optionFilterProp="label" style={{ width: 170 }} placeholder="定位族人" value={root ?? undefined}
        onChange={(id: number) => {
          setRoot(id)
          const p = scene.nodes.find(n => n.id === id)
          if (p && !directOnly) setOffset({ x: viewport.width / 2 - (p.x + NODE_W / 2) * scale, y: viewport.height / 2 - (p.y + NODE_H / 2) * scale })
        }} options={nodes.map(n => ({ value: n.id, label: `第${n.generation}世 ${n.name}` }))} />
      <Space size={4}>
        <Tooltip title="缩小"><Button aria-label="缩小" size="small" icon={<ZoomOutOutlined />} onClick={() => zoom(scale / 1.15)} /></Tooltip>
        <Tooltip title="放大"><Button aria-label="放大" size="small" icon={<ZoomInOutlined />} onClick={() => zoom(scale * 1.15)} /></Tooltip>
        <Tooltip title="适应画布"><Button aria-label="适应画布" size="small" icon={<CompressOutlined />} onClick={fit} /></Tooltip>
        <Button size="small" onClick={() => zoom(1)}>100%</Button>
      </Space>
      <InputNumber aria-label="导出边距" size="small" min={0} max={200} value={exportMargin} onChange={v => setExportMargin(Number(v ?? 40))} addonBefore="边距" style={{ width: 110 }} />
      <Button size="small" icon={<DownloadOutlined />} onClick={() => exportImage('png')}>PNG</Button>
      <Button size="small" onClick={() => exportImage('jpg')}>JPG</Button>
      <Button size="small" onClick={() => exportImage('svg')}>SVG</Button>
    </Space>}>
      <Space wrap style={{ marginBottom: 8 }}>
        <span>只看直系 <Switch aria-label="只看直系" checked={directOnly} onChange={setDirectOnly} size="small" /></span>
        <Tag>显示 {scene.nodes.length} / 共 {nodes.length} 位族人</Tag><Tag color="blue">缩放 {(scale * 100).toFixed(0)}%</Tag>
        {selected && <Button size="small" onClick={() => setSelected(null)}>取消关系高亮</Button>}
      </Space>
      {scene.warnings.length > 0 && <Alert type="warning" showIcon style={{ marginBottom: 8 }} message="关系资料需要核对"
        description={scene.warnings.join('；')} />}
      <div ref={canvasRef} data-testid="pedigree-canvas" style={{ border: '1px solid #eee', background: '#fff', height: '65vh', minHeight: 420, overflow: 'hidden', borderRadius: 8, touchAction: 'none' }}
        onPointerDown={onPointerDown} onPointerMove={onPointerMove} onPointerUp={() => { drag.current = null }} onPointerCancel={() => { drag.current = null }}
        onTouchStart={e => { if (e.touches.length === 2) { pinch.current = { dist: touchDist(e.touches), scale }; drag.current = null } }}
        onTouchMove={e => { if (e.touches.length === 2 && pinch.current) { e.preventDefault(); zoom(pinch.current.scale * touchDist(e.touches) / pinch.current.dist) } }}
        onTouchEnd={() => { pinch.current = null }}>
        <svg ref={svgRef} width="100%" height="100%" style={{ cursor: 'grab' }} role="img" aria-label="家谱关系图">
          <defs>
            <marker id="fts-child-arrow" viewBox="0 0 10 10" refX="10" refY="5" markerWidth="7" markerHeight="7" orient="auto" markerUnits="strokeWidth">
              <path d="M 0 0 L 10 5 L 0 10 Z" fill="#4c79a3" />
            </marker>
          </defs>
          <g data-scene="true" transform={`translate(${offset.x} ${offset.y}) scale(${scale})`}>
            {scene.areas.map(a => <g key={a.id} data-family-area={a.id} pointerEvents="none">
              <rect x={a.x} y={a.y} width={a.width} height={a.height} rx={10} fill="#faf9f6" stroke="#e7e0d6" strokeDasharray="4 5" />
              <text x={a.x + 10} y={a.y + 17} fontSize={11} fill="#8a8075">{a.label}</text>
            </g>)}
            {scene.edges.map(e => {
              const spouse = e.kind === 'marriage', common = e.kind === 'coparent', m = e.labelAt || middle(e.points)
              const active = !selected || e.memberIds.includes(selected.id) || e.memberIds.every(id => related.has(id))
              const color = spouse ? '#cf8241' : common ? '#8a8096' : '#4c79a3'
              return <g key={e.id} data-edge={e.id} data-kind={e.kind} data-source={e.sourceId} data-target={e.targetId} opacity={active ? 1 : .17}>
                <title>{e.title}</title>
                <path d={pathOf(e.points)} fill="none" stroke={color} strokeWidth={spouse ? 2 : 1.6} markerEnd={e.arrow ? "url(#fts-child-arrow)" : undefined} strokeDasharray={common ? '2 4' : e.special ? '6 4' : undefined} />
                {e.label && <text x={m.x} y={m.y} textAnchor="middle" fontSize={11} fill={color} stroke="#fff" strokeWidth={4} paintOrder="stroke">{e.label.length > 24 ? e.label.slice(0, 23) + '…' : e.label}</text>}
              </g>
            })}
            {scene.nodes.map(l => <g key={l.id} data-person={l.id} transform={`translate(${l.x} ${l.y})`} opacity={!selected || related.has(l.id) ? 1 : .35}
              onClick={() => { if (!moved.current) setSelected(l.node) }} style={{ cursor: 'pointer' }}>
              <title>{l.node.name} · 第{l.node.generation}世 · {PERSON_TYPES[l.node.type]}</title>
              <rect width={NODE_W} height={NODE_H} rx={7} fill={[1, 4, 5].includes(l.node.type) ? '#f4f0e8' : '#fdf3f0'}
                stroke={selected?.id === l.id ? '#8c6b4f' : '#d9cdbd'} strokeWidth={selected?.id === l.id ? 2.5 : 1} />
              <text x={NODE_W / 2} y={25} textAnchor="middle" fontSize={14} fill="#333">{l.node.name.length > 9 ? l.node.name.slice(0, 8) + '…' : l.node.name}</text>
              <text x={NODE_W / 2} y={45} textAnchor="middle" fontSize={11} fill="#777">第{l.node.generation}世 · {PERSON_TYPES[l.node.type]}</text>
            </g>)}
            <g data-legend="true" transform={`translate(${content.minX + 8} ${bounds.maxY + 20})`} fontSize={11} fill="#666">
              <path d="M 0 0 H 24" stroke="#cf8241" strokeWidth={2} /><text x={30} y={4}>夫妻</text>
              <path d="M 74 0 H 98" stroke="#4c79a3" strokeWidth={1.6} markerEnd="url(#fts-child-arrow)" /><text x={104} y={4}>亲生</text>
              <path d="M 148 0 H 172" stroke="#4c79a3" strokeDasharray="6 4" markerEnd="url(#fts-child-arrow)" /><text x={178} y={4}>其他生养关系（见标注）</text>
              <path d="M 330 0 H 354" stroke="#8a8096" strokeDasharray="2 4" /><text x={360} y={4}>共同父母</text>
            </g>
          </g>
        </svg>
      </div>

      {selected && (mobile ? (
        <Drawer
          placement="bottom"
          height={190}
          open
          onClose={() => setSelected(null)}
          title={`${selected.name} 详情`}
        >
          <Space wrap>
            <Tag>世代：{selected.generation}</Tag>
            <Tag>类型：{PERSON_TYPES[selected.type]}</Tag>
            <Tag>生卒：{selected.birth_date || '?'} ~ {selected.death_date || '在世'}</Tag>
            {selected.courtesy_name && <Tag>字：{selected.courtesy_name}</Tag>}
            <Tag>子女 {selected.children.length} 人</Tag>
          </Space>
        </Drawer>
      ) : (
        <Card size="small" style={{ marginTop: 12 }} title={`${selected.name} 详情`}>
          <Space wrap>
            <Tag>世代：{selected.generation}</Tag>
            <Tag>类型：{PERSON_TYPES[selected.type]}</Tag>
            <Tag>生卒：{selected.birth_date || '?'} ~ {selected.death_date || '在世'}</Tag>
            {selected.courtesy_name && <Tag>字：{selected.courtesy_name}</Tag>}
            <Tag>子女 {selected.children.length} 人</Tag>
          </Space>
        </Card>
      ))}
    </Card>
  )
}
