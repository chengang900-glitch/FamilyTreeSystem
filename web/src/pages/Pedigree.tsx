import { useEffect, useMemo, useRef, useState } from 'react'
import {
  Button, Card, Select, Space, Switch, Tag, Tooltip, message,
} from 'antd'
import { DownloadOutlined, ZoomInOutlined, ZoomOutOutlined, CompressOutlined } from '@ant-design/icons'
import { api } from '../api'
import { useStore } from '../store'
import { PERSON_TYPES } from '../constants'
import {
  Laid, PNode, boundsOf, edgesOf, layoutOf, NODE_H, NODE_W,
} from '../pedigree/layout'

const LAYOUTS = [
  { value: 'tree', label: '树形图' },
  { value: 'ring', label: '环状图' },
  { value: 'fan', label: '扇形图' },
  { value: 'spine', label: '直系延展图' },
  { value: 'side', label: '并排式' },
]

export default function Pedigree() {
  const { familyId } = useStore()
  const [nodes, setNodes] = useState<PNode[]>([])
  const [root, setRoot] = useState<number | null>(null)
  const [layout, setLayout] = useState('tree')
  const [orientation, setOrientation] = useState<'vertical' | 'horizontal'>('vertical')
  const [directOnly, setDirectOnly] = useState(false)
  const [scale, setScale] = useState(1)
  const [offset, setOffset] = useState({ x: 0, y: 0 })
  const [selected, setSelected] = useState<PNode | null>(null)
  const svgRef = useRef<SVGSVGElement>(null)
  const drag = useRef<{ x: number; y: number; ox: number; oy: number } | null>(null)

  const load = async () => {
    if (!familyId) return
    try {
      const d = await api.get(`/api/families/${familyId}/pedigree`)
      setNodes(d.nodes)
      setRoot(d.root)
    } catch (e: any) {
      message.error(e.message)
    }
  }

  useEffect(() => {
    load()
  }, [familyId])

  const laid = useMemo(
    () => layoutOf(layout, nodes, root as number, orientation, directOnly),
    [layout, nodes, root, orientation, directOnly],
  )
  const edges = useMemo(() => edgesOf(nodes, laid), [nodes, laid])
  const bounds = useMemo(() => boundsOf(laid), [laid])
  const width = Math.max(bounds.maxX - bounds.minX + NODE_W * 2 + 80, 800)
  const height = Math.max(bounds.maxY - bounds.minY + NODE_H * 2 + 80, 500)
  const padX = bounds.minX - NODE_W
  const padY = bounds.minY - NODE_H

  const fit = () => {
    const box = svgRef.current?.parentElement
    if (!box) return
    const sx = (box.clientWidth - 40) / width
    const sy = (box.clientHeight - 40) / height
    setScale(Math.min(sx, sy, 1.4))
    setOffset({ x: 0, y: 0 })
  }

  useEffect(() => {
    const t = setTimeout(fit, 50)
    return () => clearTimeout(t)
  }, [width, height])

  const onWheel = (e: React.WheelEvent) => {
    e.preventDefault()
    setScale((s) => Math.min(Math.max(s * (e.deltaY > 0 ? 0.9 : 1.1), 0.2), 4))
  }

  const onPointerDown = (e: React.PointerEvent) => {
    drag.current = { x: e.clientX, y: e.clientY, ox: offset.x, oy: offset.y }
    ;(e.target as Element).setPointerCapture?.(e.pointerId)
  }
  const onPointerMove = (e: React.PointerEvent) => {
    if (!drag.current) return
    setOffset({
      x: drag.current.ox + (e.clientX - drag.current.x),
      y: drag.current.oy + (e.clientY - drag.current.y),
    })
  }
  const onPointerUp = () => {
    drag.current = null
  }

  const pinch = useRef<{ dist: number; scale: number } | null>(null)
  // React 的 TouchList 与 DOM lib 的 TouchList 不是同一个类型，这里只取需要的两个字段
  const touchDist = (t: ArrayLike<{ clientX: number; clientY: number }>) =>
    Math.hypot(t[0].clientX - t[1].clientX, t[0].clientY - t[1].clientY)

  const onTouchStart = (e: React.TouchEvent) => {
    if (e.touches.length === 2) pinch.current = { dist: touchDist(e.touches), scale }
  }
  const onTouchMove = (e: React.TouchEvent) => {
    if (e.touches.length !== 2 || !pinch.current) return
    e.preventDefault()
    const d = touchDist(e.touches)
    setScale(Math.min(Math.max(pinch.current.scale * (d / pinch.current.dist), 0.2), 4))
  }
  const onTouchEnd = () => {
    pinch.current = null
  }

  const exportImage = async (fmt: 'png' | 'jpg' | 'svg') => {
    const svg = svgRef.current
    if (!svg) return
    const margin = 40
    const clone = svg.cloneNode(true) as SVGSVGElement
    clone.setAttribute('width', String(width))
    clone.setAttribute('height', String(height))
    clone.setAttribute('xmlns', 'http://www.w3.org/2000/svg')
    const bg = document.createElementNS('http://www.w3.org/2000/svg', 'rect')
    bg.setAttribute('width', '100%')
    bg.setAttribute('height', '100%')
    bg.setAttribute('fill', fmt === 'jpg' ? '#ffffff' : '#ffffff')
    clone.insertBefore(bg, clone.firstChild)
    const xml = new XMLSerializer().serializeToString(clone)

    if (fmt === 'svg') {
      const blob = new Blob([xml], { type: 'image/svg+xml' })
      const a = document.createElement('a')
      a.href = URL.createObjectURL(blob)
      a.download = `世系树_${layout}.svg`
      a.click()
      return
    }
    const img = new Image()
    const url = URL.createObjectURL(new Blob([xml], { type: 'image/svg+xml' }))
    img.onload = () => {
      const canvas = document.createElement('canvas')
      canvas.width = (width + margin * 2) * 2
      canvas.height = (height + margin * 2) * 2
      const ctx = canvas.getContext('2d')!
      ctx.fillStyle = '#fff'
      ctx.fillRect(0, 0, canvas.width, canvas.height)
      ctx.drawImage(img, margin * 2, margin * 2, width * 2, height * 2)
      const a = document.createElement('a')
      a.href = canvas.toDataURL(fmt === 'png' ? 'image/png' : 'image/jpeg', 0.95)
      a.download = `世系树_${layout}.${fmt}`
      a.click()
      URL.revokeObjectURL(url)
    }
    img.src = url
  }

  return (
    <Card
      title="世系树"
      extra={
        <Space wrap>
          <Select
            size="small"
            style={{ width: 130 }}
            value={layout}
            onChange={setLayout}
            options={LAYOUTS}
          />
          <Select
            size="small"
            style={{ width: 100 }}
            value={orientation}
            onChange={setOrientation}
            options={[{ value: 'vertical', label: '纵向' }, { value: 'horizontal', label: '横向' }]}
          />
          <Select
            size="small"
            showSearch
            style={{ width: 160 }}
            placeholder="根节点"
            value={root ?? undefined}
            onChange={setRoot}
            options={nodes.map((n) => ({ value: n.id, label: `第${n.generation}世 ${n.name}` }))}
          />
          <Space size={4}>
            <Tooltip title="缩小"><Button size="small" icon={<ZoomOutOutlined />}
              onClick={() => setScale((s) => Math.max(s - 0.1, 0.2))} /></Tooltip>
            <Tooltip title="放大"><Button size="small" icon={<ZoomInOutlined />}
              onClick={() => setScale((s) => Math.min(s + 0.1, 4))} /></Tooltip>
            <Tooltip title="适应画布"><Button size="small" icon={<CompressOutlined />} onClick={fit} /></Tooltip>
          </Space>
          <Button size="small" icon={<DownloadOutlined />} onClick={() => exportImage('png')}>PNG</Button>
          <Button size="small" onClick={() => exportImage('jpg')}>JPG</Button>
          <Button size="small" onClick={() => exportImage('svg')}>SVG</Button>
        </Space>
      }
    >
      <Space wrap style={{ marginBottom: 8 }}>
        <Space size={4}>
          <span style={{ fontSize: 13 }}>只看直系</span>
          <Switch checked={directOnly} onChange={setDirectOnly} size="small" />
        </Space>
        <Tag>共 {nodes.length} 位族人</Tag>
        <Tag color="blue">缩放 {(scale * 100).toFixed(0)}%</Tag>
      </Space>

      <div
        style={{
          border: '1px solid #eee', background: '#fff', height: '62vh', minHeight: 380,
          overflow: 'hidden', borderRadius: 8, touchAction: 'none',
        }}
        onWheel={onWheel}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={onPointerUp}
        onTouchStart={onTouchStart}
        onTouchMove={onTouchMove}
        onTouchEnd={onTouchEnd}
      >
        <svg
          ref={svgRef}
          width="100%"
          height="100%"
          viewBox={`${padX} ${padY} ${width} ${height}`}
          style={{ cursor: 'grab' }}
        >
          <g transform={`translate(${offset.x} ${offset.y}) scale(${scale})`}
            transform-origin={`${(bounds.minX + bounds.maxX) / 2} ${(bounds.minY + bounds.maxY) / 2}`}>
            {edges.map((e, i) => {
              const mx = (e.from.x + e.to.x) / 2
              return (
                <path
                  key={i}
                  d={`M ${e.from.x + NODE_W / 2} ${e.from.y} C ${mx} ${e.from.y}, ${mx} ${e.to.y}, ${e.to.x + NODE_W / 2} ${e.to.y}`}
                  fill="none"
                  stroke="#c9b49a"
                  strokeWidth={1.5}
                />
              )
            })}
            {laid.map((l: Laid) => {
              const male = l.node.type === 1 || l.node.type === 4
              return (
                <g key={l.id} transform={`translate(${l.x} ${l.y})`} onClick={() => setSelected(l.node)}
                  style={{ cursor: 'pointer' }}>
                  <rect
                    width={NODE_W}
                    height={NODE_H}
                    rx={6}
                    fill={male ? '#f4f0e8' : '#fdf3f0'}
                    stroke={selected?.id === l.id ? '#8c6b4f' : '#d9cdbd'}
                    strokeWidth={selected?.id === l.id ? 2 : 1}
                  />
                  <text x={NODE_W / 2} y={NODE_H / 2 - 4} textAnchor="middle" fontSize={13} fill="#333">
                    {l.node.name}
                  </text>
                  <text x={NODE_W / 2} y={NODE_H / 2 + 12} textAnchor="middle" fontSize={10} fill="#999">
                    第{l.node.generation}世 · {PERSON_TYPES[l.node.type]}
                  </text>
                </g>
              )
            })}
          </g>
        </svg>
      </div>

      {selected && (
        <Card size="small" style={{ marginTop: 12 }} title={`${selected.name} 详情`}>
          <Space wrap>
            <Tag>世代：{selected.generation}</Tag>
            <Tag>类型：{PERSON_TYPES[selected.type]}</Tag>
            <Tag>生卒：{selected.birth_date || '?'} ~ {selected.death_date || '在世'}</Tag>
            {selected.courtesy_name && <Tag>字：{selected.courtesy_name}</Tag>}
            <Tag>子女 {selected.children.length} 人</Tag>
          </Space>
        </Card>
      )}
    </Card>
  )
}
