export interface Point { x: number; y: number }
export interface Rect { x: number; y: number; width: number; height: number }

/** 卡片边界可以连接，卡片内部不能走线。 */
export function blocked(a: Point, b: Point, cards: Rect[]): boolean {
  return cards.some(r => a.x === b.x
    ? a.x > r.x + .1 && a.x < r.x + r.width - .1 && Math.max(a.y, b.y) > r.y + .1 && Math.min(a.y, b.y) < r.y + r.height - .1
    : a.y > r.y + .1 && a.y < r.y + r.height - .1 && Math.max(a.x, b.x) > r.x + .1 && Math.min(a.x, b.x) < r.x + r.width - .1)
}
export function simplify(points: Point[]): Point[] {
  const out: Point[] = []
  points.forEach(p => {
    if (out.length && out[out.length - 1].x === p.x && out[out.length - 1].y === p.y) return
    while (out.length > 1) {
      const a = out[out.length - 2], b = out[out.length - 1]
      if ((a.x === b.x && b.x === p.x) || (a.y === b.y && b.y === p.y)) out.pop()
      else break
    }
    out.push(p)
  })
  return out
}

/** 优先短折线；复杂家庭再沿卡片外围的正交网格搜索，所有节点/线使用同一坐标系。 */
export function route(a: Point, b: Point, cards: Rect[]): Point[] {
  if (a.x === b.x && a.y === b.y) return [a, b]
  const mx = (a.x + b.x) / 2, my = (a.y + b.y) / 2
  const candidates = [
    [a, { x: a.x, y: my }, { x: b.x, y: my }, b],
    [a, { x: mx, y: a.y }, { x: mx, y: b.y }, b],
    [a, { x: a.x, y: b.y }, b], [a, { x: b.x, y: a.y }, b],
  ]
  const direct = candidates.find(p => p.slice(1).every((q, i) => !blocked(p[i], q, cards)))
  if (direct) return simplify(direct)
  const xs = [...new Set([a.x, b.x, ...cards.flatMap(r => [r.x - 16, r.x + r.width + 16])])].sort((x, y) => x - y)
  const ys = [...new Set([a.y, b.y, ...cards.flatMap(r => [r.y - 16, r.y + r.height + 16])])].sort((x, y) => x - y)
  const ny = ys.length, start = xs.indexOf(a.x) * ny + ys.indexOf(a.y), end = xs.indexOf(b.x) * ny + ys.indexOf(b.y)
  const point = (i: number) => ({ x: xs[Math.floor(i / ny)], y: ys[i % ny] })
  const dist = new Map<number, number>([[start, 0]]), prev = new Map<number, number>()
  const heap: { id: number; score: number }[] = []
  const push = (id: number, score: number) => {
    heap.push({ id, score }); let i = heap.length - 1
    while (i > 0) { const p = (i - 1) >> 1; if (heap[p].score <= score) break; [heap[i], heap[p]] = [heap[p], heap[i]]; i = p }
  }
  const pop = () => {
    const first = heap[0], last = heap.pop()!
    if (heap.length) {
      heap[0] = last; let i = 0
      while (i * 2 + 1 < heap.length) {
        let c = i * 2 + 1
        if (c + 1 < heap.length && heap[c + 1].score < heap[c].score) c++
        if (heap[i].score <= heap[c].score) break
        ;[heap[i], heap[c]] = [heap[c], heap[i]]; i = c
      }
    }
    return first.id
  }
  push(start, 0)
  const closed = new Set<number>()
  while (heap.length) {
    const id = pop(); if (closed.has(id)) continue
    if (id === end) {
      const result = [b]; let cur = end
      while (cur !== start) { cur = prev.get(cur)!; result.push(point(cur)) }
      return simplify(result.reverse())
    }
    closed.add(id)
    const x = Math.floor(id / ny), y = id % ny, p = point(id)
    for (const [u, v] of [[x - 1, y], [x + 1, y], [x, y - 1], [x, y + 1]]) {
      if (u < 0 || u >= xs.length || v < 0 || v >= ys.length) continue
      const next = u * ny + v, q = point(next)
      if (closed.has(next) || blocked(p, q, cards)) continue
      const cost = dist.get(id)! + Math.abs(p.x - q.x) + Math.abs(p.y - q.y)
      if (cost >= (dist.get(next) ?? Infinity)) continue
      dist.set(next, cost); prev.set(next, id)
      push(next, cost + Math.abs(q.x - b.x) + Math.abs(q.y - b.y))
    }
  }
  // 非重叠卡片外围的网格应连通；拒绝静默画出穿卡线。
  throw new Error('关系线无法避开卡片，请检查布局')
}

export function pathOf(points: Point[]): string {
  // 在卡片外的折点做小圆角，保证圆角不切入相邻卡片。
  let d = `M ${points[0].x} ${points[0].y}`
  for (let i = 1; i < points.length - 1; i++) {
    const a = points[i - 1], b = points[i], c = points[i + 1]
    const ab = Math.abs(a.x - b.x) + Math.abs(a.y - b.y), bc = Math.abs(c.x - b.x) + Math.abs(c.y - b.y)
    const r = Math.min(5, ab / 3, bc / 3)
    if (!r) continue
    const p = { x: b.x + (a.x - b.x) * r / ab, y: b.y + (a.y - b.y) * r / ab }
    const q = { x: b.x + (c.x - b.x) * r / bc, y: b.y + (c.y - b.y) * r / bc }
    d += ` L ${p.x} ${p.y} Q ${b.x} ${b.y} ${q.x} ${q.y}`
  }
  return d + ` L ${points[points.length - 1].x} ${points[points.length - 1].y}`
}
