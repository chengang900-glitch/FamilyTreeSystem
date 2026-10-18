export interface PNode {
  id: number
  name: string
  courtesy_name: string
  generation: number
  type: number
  birth_date: string
  death_date: string
  branch_id: number | null
  parents: number[]
  children: number[]
  spouses: number[]
}

export interface Laid {
  id: number
  x: number
  y: number
  node: PNode
}

const NODE_W = 96
const NODE_H = 44
const GAP_X = 18
const GAP_Y = 90

export function buildIndex(nodes: PNode[]) {
  const map = new Map<number, PNode>()
  nodes.forEach((n) => map.set(n.id, n))
  return map
}

/** 只保留直系（root 的祖先链 + 后代链）或全谱 */
export function filterLine(nodes: PNode[], root: number | null, directOnly: boolean): PNode[] {
  if (!directOnly || !root) return nodes
  const map = buildIndex(nodes)
  const keep = new Set<number>()
  if (!map.has(root)) return nodes

  // 迭代遍历 + 独立 visited：即使数据里有环路也不会无限递归
  const walk = (start: number, dir: 'up' | 'down') => {
    const visited = new Set<number>()
    const stack = [start]
    while (stack.length) {
      const cur = stack.pop() as number
      if (visited.has(cur)) continue
      visited.add(cur)
      const n = map.get(cur)
      if (!n) continue
      keep.add(cur)
      const next = dir === 'up' ? n.parents : n.children
      next.forEach((x) => {
        if (!visited.has(x)) stack.push(x)
      })
    }
  }
  walk(root, 'up')
  walk(root, 'down')
  return nodes.filter((n) => keep.has(n.id))
}

function subtreeWidth(id: number, childrenOf: Map<number, number[]>,
  memo: Map<number, number> = new Map(), stack: Set<number> = new Set()): number {
  const cached = memo.get(id)
  if (cached !== undefined) return cached
  if (stack.has(id)) return NODE_W + GAP_X
  stack.add(id)
  const kids = childrenOf.get(id) || []
  const width = kids.length
    ? kids.reduce((sum, k) => sum + subtreeWidth(k, childrenOf, memo, stack), 0)
    : NODE_W + GAP_X
  stack.delete(id)
  memo.set(id, width)
  return width
}

/** 树形图：自顶向下分层，递归均分宽度 */
export function layoutTree(nodes: PNode[], root: number, orientation: 'vertical' | 'horizontal',
  directOnly = false): Laid[] {
  const list = filterLine(nodes, root, directOnly)
  const map = buildIndex(list)
  const childrenOf = new Map<number, number[]>()
  list.forEach((n) => {
    childrenOf.set(n.id, n.children.filter((c) => map.has(c)))
  })
  const roots = root && map.has(root) ? [root] : list.filter((n) => !n.parents.some((p) => map.has(p))).map((n) => n.id)
  const out: Laid[] = []
  const memo = new Map<number, number>()
  const placed = new Set<number>()
  let cursor = 0

  const place = (id: number, depth: number, left: number) => {
    if (placed.has(id)) return
    placed.add(id)
    const kids = (childrenOf.get(id) || []).filter((k) => !placed.has(k))
    const width = Math.max(NODE_W + GAP_X,
      kids.reduce((s, k) => s + subtreeWidth(k, childrenOf, memo), 0))
    const cx = left + width / 2
    const node = map.get(id)!
    out.push({
      id,
      x: orientation === 'vertical' ? cx : depth * (NODE_W + GAP_X * 2),
      y: orientation === 'vertical' ? depth * GAP_Y : cx,
      node,
    })
    let childLeft = left
    kids.forEach((k) => {
      const w = subtreeWidth(k, childrenOf, memo)
      place(k, depth + 1, childLeft)
      childLeft += w
    })
  }

  roots.forEach((r) => {
    place(r, 0, cursor)
    cursor += subtreeWidth(r, childrenOf, memo)
  })
  return out
}

/** 环状图：世代为环，同代均分角度 */
export function layoutRing(nodes: PNode[], root: number, directOnly = false): Laid[] {
  const list = filterLine(nodes, root, directOnly)
  const byGen = new Map<number, PNode[]>()
  list.forEach((n) => {
    const arr = byGen.get(n.generation) || []
    arr.push(n)
    byGen.set(n.generation, arr)
  })
  const gens = [...byGen.keys()].sort((a, b) => a - b)
  const out: Laid[] = []
  gens.forEach((g, gi) => {
    const arr = byGen.get(g)!
    const radius = 90 + gi * 110
    arr.forEach((n, i) => {
      const angle = (2 * Math.PI * i) / arr.length
      out.push({ id: n.id, x: Math.cos(angle) * radius, y: Math.sin(angle) * radius, node: n })
    })
  })
  return out
}

/** 扇形图：半圆展开 */
export function layoutFan(nodes: PNode[], root: number, directOnly = false): Laid[] {
  const list = filterLine(nodes, root, directOnly)
  const byGen = new Map<number, PNode[]>()
  list.forEach((n) => {
    const arr = byGen.get(n.generation) || []
    arr.push(n)
    byGen.set(n.generation, arr)
  })
  const gens = [...byGen.keys()].sort((a, b) => a - b)
  const out: Laid[] = []
  gens.forEach((g, gi) => {
    const arr = byGen.get(g)!
    const radius = 110 + gi * 120
    arr.forEach((n, i) => {
      const angle = Math.PI * ((i + 0.5) / arr.length)
      out.push({ id: n.id, x: Math.cos(angle) * radius, y: -Math.sin(angle) * radius, node: n })
    })
  })
  return out
}

/** 直系延展图：直系主轴水平居中，旁系上下偏移 */
export function layoutSpine(nodes: PNode[], root: number, directOnly = false): Laid[] {
  const list = filterLine(nodes, root, directOnly)
  const map = buildIndex(list)
  const out: Laid[] = []
  const visited = new Set<number>()
  const spine: number[] = []
  let cur: number | undefined = root
  while (cur && !visited.has(cur)) {
    visited.add(cur)
    spine.push(cur)
    const n = map.get(cur)
    cur = n?.children.find((c) => map.has(c))
  }
  spine.forEach((id, i) => {
    const n = map.get(id)!
    out.push({ id, x: i * 150, y: 0, node: n })
    const others = n.children.filter((c) => map.has(c) && !spine.includes(c))
    others.forEach((c, ci) => {
      out.push({ id: c, x: i * 150, y: (ci % 2 === 0 ? -1 : 1) * (90 + Math.floor(ci / 2) * 60), node: map.get(c)! })
    })
  })
  return out
}

/** 并排式：每个世代一列，逐列排开 */
export function layoutSide(nodes: PNode[], root: number, directOnly = false): Laid[] {
  const list = filterLine(nodes, root, directOnly)
  const byGen = new Map<number, PNode[]>()
  list.forEach((n) => {
    const arr = byGen.get(n.generation) || []
    arr.push(n)
    byGen.set(n.generation, arr)
  })
  const gens = [...byGen.keys()].sort((a, b) => a - b)
  const out: Laid[] = []
  gens.forEach((g, gi) => {
    ;(byGen.get(g) || []).forEach((n, i) => {
      out.push({ id: n.id, x: gi * 160, y: i * (NODE_H + 16), node: n })
    })
  })
  return out
}

export function layoutOf(kind: string, nodes: PNode[], root: number,
  orientation: 'vertical' | 'horizontal', directOnly: boolean): Laid[] {
  if (!nodes.length || !root) return []
  switch (kind) {
    case 'ring': return layoutRing(nodes, root, directOnly)
    case 'fan': return layoutFan(nodes, root, directOnly)
    case 'spine': return layoutSpine(nodes, root, directOnly)
    case 'side': return layoutSide(nodes, root, directOnly)
    default: return layoutTree(nodes, root, orientation, directOnly)
  }
}

export function edgesOf(nodes: PNode[], laid: Laid[]) {
  const pos = new Map(laid.map((l) => [l.id, l]))
  const edges: { from: Laid; to: Laid }[] = []
  nodes.forEach((n) => {
    const to = pos.get(n.id)
    if (!to) return
    n.children.forEach((c) => {
      const from = pos.get(c)
      if (from) edges.push({ from, to })
    })
  })
  return edges
}

export function boundsOf(laid: Laid[]) {
  if (!laid.length) return { minX: 0, minY: 0, maxX: 400, maxY: 300 }
  const xs = laid.map((l) => l.x)
  const ys = laid.map((l) => l.y)
  return { minX: Math.min(...xs), minY: Math.min(...ys), maxX: Math.max(...xs), maxY: Math.max(...ys) }
}

export { NODE_W, NODE_H }
