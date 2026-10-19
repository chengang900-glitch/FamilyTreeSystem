import { route, simplify } from './routing.ts'
import type { Point, Rect } from './routing.ts'

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

const NODE_W = 144
const NODE_H = 60
const GAP_X = 48

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

export interface Marriage { id: number; spouse1_id: number; spouse2_id: number; marriage_order: number }
export interface ParentChild { id: number; parent_id: number; child_id: number; type: number; child_order?: number | null }
export interface Relations { marriages?: Marriage[]; parentchild?: ParentChild[] }
export interface Family { id: string; parents: number[]; children: { id: number; relations: ParentChild[] }[]; marriage?: Marriage; anchorId?: number }
export interface Edge {
  id: string; kind: 'marriage' | 'coparent' | 'parentchild'; memberIds: number[]
  sourceId?: number; targetId?: number; arrow: boolean
  points: Point[]; label: string; labelAt?: Point; title: string; special: boolean
}
export interface FamilyArea extends Rect { id: string; label: string; memberIds: number[] }
export interface Scene { areas: FamilyArea[]; nodes: Laid[]; families: Family[]; edges: Edge[]; warnings: string[]; bounds: ReturnType<typeof boundsOf> }
const PC: Record<number, string> = {1:'亲生',2:'过继',3:'收养',4:'继养',5:'亲女',6:'养女',7:'继女'}
const male = (n: PNode) => [1,4,5].includes(n.type)

function relationships(nodes: PNode[], relations: Relations) {
  const ids = new Set(nodes.map(n => n.id))
  const parentchild = (relations.parentchild ?? nodes.flatMap(n => n.children.map(child_id => ({id:n.id * 100000 + child_id,parent_id:n.id,child_id,type:1}))))
    .filter(e => ids.has(e.parent_id) && ids.has(e.child_id))
  const marriages = (relations.marriages ?? nodes.flatMap(n => n.spouses.filter(id => n.id < id).map(id => ({id:n.id * 100000 + id,spouse1_id:n.id,spouse2_id:id,marriage_order:1}))))
    .filter(e => ids.has(e.spouse1_id) && ids.has(e.spouse2_id))
  return {parentchild,marriages}
}

function familiesOf(nodes: PNode[], rel: ReturnType<typeof relationships>, warnings: Set<string>): Family[] {
  const map = buildIndex(nodes), families = new Map<string,Family>()
  const get = (parents: number[]) => {
    const sorted = [...parents].sort((a,b) => a-b), id = sorted.join('-')
    if (!families.has(id)) families.set(id,{id,parents:sorted,children:[]})
    return families.get(id)!
  }
  rel.marriages.forEach(m => {get([m.spouse1_id,m.spouse2_id]).marriage = m})
  const incoming = new Map<number,ParentChild[]>()
  rel.parentchild.forEach(e => {const arr=incoming.get(e.child_id)||[];arr.push(e);incoming.set(e.child_id,arr)})
  const pairable = (items: ParentChild[]) => items.length === 2 && (map.get(items[0].parent_id)!.type === undefined
    || male(map.get(items[0].parent_id)!) !== male(map.get(items[1].parent_id)!))
  incoming.forEach((edges,child) => {
    let groups: ParentChild[][]
    if (pairable(edges)) groups=[edges]
    else if (edges.length > 2) {
      const classes=new Map<number,ParentChild[]>()
      edges.forEach(e=>{const kind=[1,5].includes(e.type)?1:[3,6].includes(e.type)?3:[4,7].includes(e.type)?4:e.type;const arr=classes.get(kind)||[];arr.push(e);classes.set(kind,arr)})
      groups=[...classes.values()].flatMap(items=>pairable(items)?[items]:items.map(e=>[e]))
      if ([...classes.values()].some(items=>items.length>2)) warnings.add(`${map.get(child)!.name}存在多条同类父母关系，请核对资料；图中保留全部关系`)
    } else { groups=edges.map(e=>[e]);if(edges.length===2)warnings.add(`${map.get(child)!.name}的父母类型需核对，图中分别连接`) }
    groups.forEach(items=>get(items.map(e=>e.parent_id)).children.push({id:child,relations:items}))
  })
  return [...families.values()]
}

/** 以婚姻通道分配后代空间；配偶辅助行/列仍属于主成员所在世代。 */
function familyLayout(nodes: PNode[], families: Family[], pc: ParentChild[], kind: string,
  orientation: 'vertical'|'horizontal', warnings: Set<string>, areas: FamilyArea[] = [], focus?: number): Laid[] {
  if (!nodes.length) return []
  const map = buildIndex(nodes), owner = new Map(nodes.map(n => [n.id, n.id]))
  const find = (id: number): number => { let cur = id; while (owner.get(cur) !== cur) cur = owner.get(cur)!; return cur }
  const reaches = (a: number, b: number) => {
    const next = new Map<number, number[]>()
    pc.forEach(e => { const p = find(e.parent_id), c = find(e.child_id); if (p !== c) next.set(p, [...(next.get(p) || []), c]) })
    const stack = [a], seen = new Set<number>()
    while (stack.length) { const v = stack.pop()!; if (v === b) return true; if (seen.has(v)) continue; seen.add(v); stack.push(...(next.get(v) || [])) }
    return false
  }
  families.filter(f => f.parents.length === 2).forEach(f => {
    const [a, b] = f.parents, pa = map.get(a)!, pb = map.get(b)!, u = find(a), v = find(b)
    if (u === v) return
    if (pa.generation !== pb.generation || reaches(u, v) || reaches(v, u)) {
      warnings.add(`${pa.name}与${pb.name}的世代或亲属层级不同，已保留原资料并分别排位`); return
    }
    owner.set(v, u)
  })
  interface Lane { family: Family; members: number[]; children: number[]; span: number; left: number }
  interface Block { id: number; members: PNode[]; primary: PNode; rank: number; children: number[]; lanes: Lane[]; span: number; cross: number; primaryCross: number }
  const blocks = new Map<number, Block>()
  nodes.forEach(n => {
    const id = find(n.id)
    if (!blocks.has(id)) blocks.set(id, { id, members: [], primary: n, rank: n.generation, children: [], lanes: [], span: 0, cross: 0, primaryCross: 0 })
    blocks.get(id)!.members.push(n)
  })
  const radial = kind === 'ring' || kind === 'fan'
  const vertical = radial || orientation === 'vertical', crossSize = vertical ? NODE_W : NODE_H, depthSize = vertical ? NODE_H : NODE_W
  const spouseDown = kind === 'tree' && !vertical
  const childDrop = (lane: Lane) => spouseDown && lane.members.length && lane.children.length ? NODE_H + 56 : 0
  const minGen = Math.min(...nodes.map(n => n.generation)), auxDepth = depthSize + (vertical ? 44 : 104)
  blocks.forEach(b => {
    const degree = (id: number) => families.filter(f => f.parents.length === 2 && f.parents.includes(id)).length
    b.primary = b.members.find(n => n.id === focus) || [...b.members].sort((a, c) => degree(c.id) - degree(a.id) || c.parents.length - a.parents.length || a.id - c.id)[0]
    b.rank = Math.max(0, Math.min(...b.members.map(n => n.generation)) - minGen)
    const local = families.filter(f => f.parents.every(p => find(p) === b.id)).sort((a, c) => {
      const order = (f: Family) => f.marriage?.marriage_order ?? 10000
      return order(a) - order(c) || a.id.localeCompare(c.id, undefined, { numeric: true })
    })
    const placed = new Set([b.primary.id])
    // 先从主成员的婚姻展开，再覆盖配偶也有其他婚姻的复杂网络。
    const pending = [...local]
    while (pending.length) {
      let index = pending.findIndex(f => f.parents.some(p => placed.has(p)))
      if (index < 0) index = 0
      const f = pending.splice(index, 1)[0], members = f.parents.filter(p => !placed.has(p))
      members.forEach(p => placed.add(p))
      f.anchorId = members[members.length - 1] ?? f.parents.find(p => p !== b.primary.id) ?? f.parents[0]
      b.lanes.push({ family: f, members, children: [], span: 0, left: 0 })
    }
  })
  const outgoing = new Map<number, Set<number>>(), incoming = new Map<number, Set<number>>()
  pc.forEach(e => {
    const p = find(e.parent_id), c = find(e.child_id)
    if (map.get(e.parent_id)!.generation >= map.get(e.child_id)!.generation) warnings.add(`${map.get(e.child_id)!.name}的登记世代不晚于父母，请核对；未自动修改资料`)
    if (p === c) { warnings.add('存在家庭内部亲子层级冲突，请核对资料'); return }
    if (!outgoing.has(p)) outgoing.set(p, new Set()); outgoing.get(p)!.add(c)
    if (!incoming.has(c)) incoming.set(c, new Set()); incoming.get(c)!.add(p)
  })
  const indegree = new Map([...blocks.keys()].map(id => [id, incoming.get(id)?.size || 0]))
  const queue = [...blocks.keys()].filter(id => !indegree.get(id)).sort((a, b) => blocks.get(a)!.rank - blocks.get(b)!.rank || a - b), order: number[] = []
  for (let i = 0; i < queue.length; i++) {
    const id = queue[i]; order.push(id)
    outgoing.get(id)?.forEach(c => { blocks.get(c)!.rank = Math.max(blocks.get(c)!.rank, blocks.get(id)!.rank + 1); indegree.set(c, indegree.get(c)! - 1); if (!indegree.get(c)) queue.push(c) })
  }
  if (order.length !== blocks.size) { warnings.add('关系存在环路，请核对资料；所有成员仍保留显示'); [...blocks.keys()].filter(id => !order.includes(id)).forEach(id => order.push(id)) }
  const primaryParent = new Map<number, number>()
  order.forEach(id => {
    const parents = [...(incoming.get(id) || [])].filter(p => blocks.get(p)!.rank < blocks.get(id)!.rank)
      .sort((a, b) => blocks.get(b)!.rank - blocks.get(a)!.rank || a - b)
    if (parents.length) { primaryParent.set(id, parents[0]); blocks.get(parents[0])!.children.push(id) }
  })
  const siblingInfo = (id: number) => {
    const entries = pc.filter(e => find(e.child_id) === id && find(e.parent_id) === primaryParent.get(id))
    const orders = [...new Set(entries.map(e => e.child_order).filter((n): n is number => typeof n === 'number'))]
    if (orders.length > 1) warnings.add(`${map.get(entries[0].child_id)!.name}在双亲名下的排行不同，按各条关系保留，请核对`)
    const child = map.get(entries[0]?.child_id) || blocks.get(id)!.primary, date = child.birth_date || ''
    return { rank: orders.length === 1 ? orders[0] : Infinity, date: /^\d{4}-\d{2}-\d{2}$/.test(date) && !Number.isNaN(Date.parse(date)) ? date : '9999' }
  }
  const siblingSort = (a: number, b: number) => {
    const x = siblingInfo(a), y = siblingInfo(b)
    return (x.rank === y.rank ? 0 : x.rank < y.rank ? -1 : 1) || x.date.localeCompare(y.date) || a - b
  }
  ;[...order].reverse().forEach(id => {
    const b = blocks.get(id)!
    b.children.sort(siblingSort)
    b.children.forEach(c => {
      const lane = b.lanes.find(l => l.family.children.some(child => child.id === blocks.get(c)!.primary.id))
        || b.lanes.find(l => l.family.children.some(child => find(child.id) === c))
      if (lane) lane.children.push(c)
    })
    b.lanes.forEach(l => {
      const own = l.members.length * crossSize + Math.max(0, l.members.length - 1) * GAP_X
      const kids = l.children.reduce((s, c) => s + blocks.get(c)!.span, 0) + Math.max(0, l.children.length - 1) * GAP_X
      l.span = Math.max(crossSize, own, kids + childDrop(l))
    })
    b.span = Math.max(crossSize, b.lanes.reduce((s, l) => s + l.span, 0) + Math.max(0, b.lanes.length - 1) * GAP_X,
      radial ? b.members.length * (NODE_W + GAP_X) : 0)
    b.primaryCross = (b.span - crossSize) / 2
    let cursor = (b.span - b.lanes.reduce((s, l) => s + l.span, 0) - Math.max(0, b.lanes.length - 1) * GAP_X) / 2
    b.lanes.forEach(l => { l.left = cursor; cursor += l.span + GAP_X })
  })
  let cursor = 0
  const pending: { id: number; left: number }[] = []
  order.filter(id => !primaryParent.has(id)).forEach(id => { pending.push({ id, left: cursor }); cursor += blocks.get(id)!.span + GAP_X * 2 })
  for (let i = 0; i < pending.length; i++) {
    const { id, left } = pending[i], b = blocks.get(id)!; b.cross = left
    b.lanes.forEach(l => {
      const total = l.children.reduce((s, c) => s + blocks.get(c)!.span, 0) + Math.max(0, l.children.length - 1) * GAP_X
      const drop = childDrop(l)
      let childLeft = left + l.left + drop + (l.span - drop - total) / 2
      l.children.forEach(c => { pending.push({ id: c, left: childLeft }); childLeft += blocks.get(c)!.span + GAP_X })
    })
    // 不属于可确定双亲组合的跨世代关联仍保留，几何上给予独立空间。
    b.children.filter(c => !b.lanes.some(l => l.children.includes(c))).forEach(c => { pending.push({ id: c, left: cursor }); cursor += blocks.get(c)!.span + GAP_X * 2 })
  }
  if (kind === 'side' || kind === 'spine') {
    const rows = new Map<number, Block[]>()
    blocks.forEach(b => rows.set(b.rank, [...(rows.get(b.rank) || []), b]))
    const main = new Set<number>()
    if (kind === 'spine') {
      let id = find(focus && map.has(focus) ? focus : nodes[0].id)
      while (primaryParent.has(id)) id = primaryParent.get(id)!
      const focusPath = new Set<number>(); let f = find(focus && map.has(focus) ? focus : nodes[0].id)
      while (!focusPath.has(f)) { focusPath.add(f); if (!primaryParent.has(f)) break; f = primaryParent.get(f)! }
      while (!main.has(id)) { main.add(id); const kids = blocks.get(id)!.children; const next = kids.find(c => focusPath.has(c)) ?? kids[0]; if (next === undefined) break; id = next }
    }
    rows.forEach(row => {
      row.sort((a, b) => a.cross - b.cross)
      const axis = row.find(b => main.has(b.id))
      let x = axis ? axis.span - axis.primaryCross + GAP_X * 2 : 0
      if (axis) axis.cross = -axis.primaryCross
      row.filter(b => b !== axis).forEach(b => { b.cross = x; x += b.span + GAP_X * 2 })
    })
  }
  const levels = [...new Set([...blocks.values()].map(b => b.rank))].sort((a, b) => a - b), depths = new Map<number, number>()
  let depth = 0
  levels.forEach(rank => {
    depths.set(rank, depth)
    const hasAux = [...blocks.values()].some(b => b.rank === rank && b.members.length > 1)
    // 横向树的下一代落在配偶正下方；下一代的配偶再向右展开。
    depth += spouseDown ? auxDepth : depthSize + (hasAux ? auxDepth : 0) + 104
  })
  let out: Laid[] = []
  blocks.forEach(b => {
    const local = new Map<number, { cross: number; depth: number }>([[b.primary.id, { cross: b.primaryCross, depth: 0 }]])
    b.lanes.forEach(l => {
      const own = l.members.length * crossSize + Math.max(0, l.members.length - 1) * GAP_X
      l.members.forEach((id, i) => local.set(id, { cross: l.left + (childDrop(l) ? 0 : (l.span - own) / 2) + i * (crossSize + GAP_X), depth: auxDepth }))
    })
    b.members.forEach((n, i) => {
      const p = local.get(n.id) || { cross: i * (crossSize + GAP_X), depth: auxDepth }
      out.push({ id: n.id, node: n, x: vertical ? b.cross + p.cross : depths.get(b.rank)! + p.depth,
        y: vertical ? depths.get(b.rank)! + p.depth : b.cross + p.cross })
    })
    // 横向树的不同世代会共用一列，不能用大矩形把其中的后代标成同代。
    if (b.members.length > 1 && !radial && !spouseDown) {
      const group = out.filter(n => find(n.id) === b.id), x = Math.min(...group.map(n => n.x)) - 16, y = Math.min(...group.map(n => n.y)) - 32
      areas.push({ id: String(b.id), x, y, width: Math.max(...group.map(n => n.x + NODE_W)) - x + 16,
        height: Math.max(...group.map(n => n.y + NODE_H)) - y + 16, memberIds: b.members.map(n => n.id), label: `第${b.primary.generation}世 · 同代` })
    }
  })
  if (radial) {
    out = []
    const forestWidth = Math.max(1, ...[...blocks.values()].map(b => b.cross + b.span))
    let radius = 210
    levels.forEach((rank, index) => {
      const row = [...blocks.values()].filter(b => b.rank === rank).sort((a, b) => a.cross - b.cross)
      const sweep = kind === 'fan' ? Math.PI * .8 : Math.PI * 1.8
      const occupiedRadius = Math.max(0, ...out.map(n => Math.hypot(n.x + NODE_W / 2, n.y + NODE_H / 2)))
      radius = Math.max(radius, forestWidth / sweep, occupiedRadius + Math.hypot(NODE_W, NODE_H) + 30)
      let generation: Laid[] = []
      for (let attempt = 0; attempt < 100; attempt++) {
        generation = []
        row.forEach(b => {
          const angle = Math.PI / 2 + ((b.cross + b.span / 2) / forestWidth - .5) * sweep
          const members = [b.primary, ...b.lanes.flatMap(l => l.members.map(id => map.get(id)!))]
          const unique = [...new Map(members.map(n => [n.id, n])).values()]
          const r = index === 0 && row.length === 1 && unique.length === 1 ? 0 : radius
          unique.forEach((n, i) => {
            const shift = (i - (unique.length - 1) / 2) * (NODE_W + GAP_X)
            generation.push({ id: n.id, node: n, x: Math.cos(angle) * r + Math.sin(angle) * shift - NODE_W / 2,
              y: Math.sin(angle) * r - Math.cos(angle) * shift - NODE_H / 2 })
          })
        })
        const collides = generation.some((a, i) => [...out, ...generation.slice(0, i)].some(b =>
          a.x < b.x + NODE_W + 12 && a.x + NODE_W + 12 > b.x && a.y < b.y + NODE_H + 12 && a.y + NODE_H + 12 > b.y))
        if (!collides) break
        radius += NODE_W + 80
      }
      out.push(...generation)
      radius += NODE_W + 100
    })
  }

  return out.sort((a, b) => a.id - b.id)
}

function middle(points: Point[]): Point {
  let best=0,p=points[0]
  for(let i=1;i<points.length;i++){const a=points[i-1],b=points[i],len=Math.abs(a.x-b.x)+Math.abs(a.y-b.y);if(len>best){best=len;p={x:(a.x+b.x)/2,y:(a.y+b.y)/2}}}
  return p
}
export function boundsOf(laid:Laid[], edges:Edge[]=[]){
  const pts=[...laid.flatMap(n=>[{x:n.x,y:n.y},{x:n.x+NODE_W,y:n.y+NODE_H}]),...edges.flatMap(e=>[...e.points,...(e.labelAt?[{x:e.labelAt.x-Math.min(24,e.label.length)*4.5-4,y:e.labelAt.y-12},{x:e.labelAt.x+Math.min(24,e.label.length)*4.5+4,y:e.labelAt.y+4}]:[])])]
  if(!pts.length)return {minX:0,minY:0,maxX:400,maxY:300}
  return {minX:Math.min(...pts.map(p=>p.x))-24,minY:Math.min(...pts.map(p=>p.y))-28,maxX:Math.max(...pts.map(p=>p.x))+24,maxY:Math.max(...pts.map(p=>p.y))+24}
}

export function buildScene(kind:string,nodes:PNode[],root:number,orientation:'vertical'|'horizontal',directOnly=false,relations:Relations={}):Scene {
  const list=filterLine(nodes,root,directOnly),warnings=new Set<string>(),rel=relationships(list,relations)
  const families=familiesOf(list,rel,warnings)
  const effective=kind==='spine'?'horizontal':orientation
  const areas:FamilyArea[]=[]
  const laid=familyLayout(list,families,rel.parentchild,kind,effective,warnings,areas,root),pos=new Map(laid.map(n=>[n.id,n]))
  const cards:Rect[]=laid.map(n=>({...n,width:NODE_W,height:NODE_H})),edges:Edge[]=[]
  const vertical=effective==='vertical'&&kind!=='ring'&&kind!=='fan'
  const radial=kind==='ring'||kind==='fan'
  const port=(n:Laid,side:'top'|'bottom'|'left'|'right')=>({x:n.x+(side==='left'?0:side==='right'?NODE_W:NODE_W/2),y:n.y+(side==='top'?0:side==='bottom'?NODE_H:NODE_H/2)})
  const names=(ids:number[])=>ids.map(id=>pos.get(id)!.node.name).join('、')
  const facing = (n:Laid, target:Point) => {
    const dx=target.x-(n.x+NODE_W/2),dy=target.y-(n.y+NODE_H/2)
    return Math.abs(dx)/NODE_W>Math.abs(dy)/NODE_H ? (dx>0?'right':'left') : (dy>0?'bottom':'top')
  }
  const escape = (p:Point, side:'top'|'bottom'|'left'|'right', distance=16) => ({x:p.x+(side==='left'?-distance:side==='right'?distance:0),y:p.y+(side==='top'?-distance:side==='bottom'?distance:0)})
  families.forEach((f,fi)=>{
    const parents=f.parents.map(id=>pos.get(id)!).filter(Boolean)
    const anchor=pos.get(f.anchorId!) || [...parents].sort((a,b)=>vertical?b.y-a.y:b.x-a.x)[0]
    if(parents.length===2){
      const [a,b]=parents
      let first=a,last=b,startSide:'top'|'bottom'|'left'|'right',endSide:typeof startSide
      if(radial){
        startSide=facing(a,{x:b.x+NODE_W/2,y:b.y+NODE_H/2});endSide=facing(b,{x:a.x+NODE_W/2,y:a.y+NODE_H/2})
      }else if(vertical ? a.y!==b.y : a.x!==b.x){
        ;[first,last]=[a,b].sort((p,q)=>vertical?p.y-q.y:p.x-q.x)
        startSide=vertical?'bottom':'right';endSide=vertical?'top':'left'
      }else{
        ;[first,last]=[a,b].sort((p,q)=>vertical?p.x-q.x:p.y-q.y)
        startSide=vertical?'right':'bottom';endSide=vertical?'left':'top'
      }
      const start=port(first,startSide),end=port(last,endSide)
      const points=simplify([start,...route(escape(start,startSide,radial?8:16),escape(end,endSide,radial?8:16),cards),end])
      const title=f.marriage?`${names(f.parents)}：婚姻（${pos.get(f.marriage.spouse1_id)!.node.name}的第${f.marriage.marriage_order}段）`:`${names(f.parents)}：共同父母，未登记婚姻`
      edges.push({id:`family-${f.id}`,kind:f.marriage?'marriage':'coparent',memberIds:f.parents,points,label:f.marriage?`夫妻 · 第${f.marriage.marriage_order}段`:'共同父母',title,special:false,arrow:false})
    }
    const childPositions=f.children.map(c=>pos.get(c.id)!).filter(Boolean)
    const minDepth=Math.min(...childPositions.map(c=>vertical?c.y:c.x))
    const household=areas.find(a=>a.memberIds.includes(anchor.id))
    const parentDepth=Math.max(...parents.map(p=>vertical?p.y+NODE_H:p.x+NODE_W),household?(vertical?household.y+household.height-16:household.x+household.width-16):-Infinity)
    const bus=parentDepth+Math.max(24,(minDepth-parentDepth)/2)+(fi%3)*10
    f.children.forEach(child=>{
      const n=pos.get(child.id)!
      // 横向树也从已登记双亲中的配偶底部接出，子女在该婚姻分组下方。
      const fromSpouseBelow=kind==='tree' && !vertical && f.parents.length===2
      const startSide=radial?facing(anchor,{x:n.x+NODE_W/2,y:n.y+NODE_H/2}):vertical||fromSpouseBelow?'bottom':'right'
      const endSide=radial?facing(n,{x:anchor.x+NODE_W/2,y:anchor.y+NODE_H/2}):vertical||fromSpouseBelow?'top':'left'
      const start=port(anchor,startSide),end=port(n,endSide),from=escape(start,startSide,radial?8:16),to=escape(end,endSide,radial?8:16)
      let points:Point[]
      if(fromSpouseBelow){
        // 单个子女直接向下；多个子女使用配偶左侧的公共分叉线，避免穿过兄姐卡片。
        const via={x:anchor.x-24,y:from.y},branch={x:via.x,y:to.y}
        points=childPositions.length===1?simplify([start,...route(from,to,cards),end])
          :simplify([start,...route(from,via,cards),...route(via,branch,cards).slice(1),...route(branch,to,cards).slice(1),end])
      }
      else if(radial)points=simplify([start,...route(from,to,cards),end])
      else{
        const via=vertical?{x:from.x,y:bus}:{x:bus,y:from.y}
        const branch=vertical?{x:to.x,y:bus}:{x:bus,y:to.y}
        points=simplify([start,...route(from,via,cards),...route(via,branch,cards).slice(1),...route(branch,to,cards).slice(1),end])
      }
      const types=[...new Set(child.relations.map(e=>e.type))],special=types.some(t=>![1,5].includes(t))
      const typeLabel=types.length===1?(types[0]===1?'':PC[types[0]]):child.relations.map(e=>`${pos.get(e.parent_id)!.node.name}：${PC[e.type]}`).join(' / ')
      const ranks=[...new Set(child.relations.map(e=>e.child_order).filter((n):n is number=>typeof n==='number'))]
      const label=[ranks.length===1?`排行 ${ranks[0]}`:'',typeLabel].filter(Boolean).join(' · ')
      edges.push({id:`child-${f.id}-${child.id}`,kind:'parentchild',memberIds:[...f.parents,child.id],sourceId:anchor.id,targetId:child.id,points,label,
        title:child.relations.map(e=>`${names([e.parent_id])} → ${n.node.name}：${PC[e.type]}${e.child_order?`，排行 ${e.child_order}`:''}`).join('；'),special,arrow:true})
    })
  })
  const labels: Rect[]=[]
  edges.forEach(e=>{
    if(!e.label)return
    const points=e.points, last=points[points.length-1], before=points[points.length-2]
    const preferred=e.kind==='parentchild'?{x:(last.x+before.x)/2,y:(last.y+before.y)/2}:middle(points)
    const mids=[preferred,...points.slice(1).map((p,i)=>({x:(p.x+points[i].x)/2,y:(p.y+points[i].y)/2}))]
    const w=Math.min(24,e.label.length)*9+8
    for(const m of mids)for(const dy of [-7,17,-40,50,-72,82]){
      const at={x:m.x,y:m.y+dy},rect={x:at.x-w/2,y:at.y-12,width:w,height:16}
      if([...cards,...labels].some(r=>rect.x<r.x+r.width&&rect.x+rect.width>r.x&&rect.y<r.y+r.height&&rect.y+rect.height>r.y))continue
      if(!e.labelAt){e.labelAt=at;labels.push(rect)}
    }
    e.labelAt??={x:preferred.x,y:preferred.y-7}
  })
  const bounds=boundsOf(laid,edges)
  areas.forEach(a=>{bounds.minX=Math.min(bounds.minX,a.x-12);bounds.minY=Math.min(bounds.minY,a.y-12);bounds.maxX=Math.max(bounds.maxX,a.x+a.width+12);bounds.maxY=Math.max(bounds.maxY,a.y+a.height+12)})
  return {areas,nodes:laid,families,edges,warnings:[...warnings],bounds}
}

export function layoutOf(kind:string,nodes:PNode[],root:number,orientation:'vertical'|'horizontal',directOnly:boolean):Laid[]{
  const list=filterLine(nodes,root,directOnly),warnings=new Set<string>(),rel=relationships(list,{})
  return familyLayout(list,familiesOf(list,rel,warnings),rel.parentchild,kind,kind==='spine'?'horizontal':orientation,warnings,[],root)
}
export { NODE_W, NODE_H, middle }
