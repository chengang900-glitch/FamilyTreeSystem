import assert from 'node:assert/strict'
import { buildScene, layoutOf, filterLine, NODE_W, NODE_H } from '../web/src/pedigree/layout.ts'

const node = (id, generation, type, parents = [], children = [], spouses = []) =>
  ({ id, generation, type, parents, children, spouses, name: `成员${id}` })
const nodes = [node(1,1,1,[],[2]), node(2,2,1,[1],[4,5],[3]), node(3,2,3,[],[4,5],[2]),
  node(4,3,1,[2,3],[7],[6]),node(5,3,1,[2,3],[]),node(6,3,3,[],[7],[4]),node(7,4,1,[4,6],[]) ]
const pc = nodes.flatMap(n=>n.children.map(child_id=>({id:n.id*100+child_id,parent_id:n.id,child_id,type:1})))
const marriages=[{id:1,spouse1_id:2,spouse2_id:3,marriage_order:1},{id:2,spouse1_id:4,spouse2_id:6,marriage_order:1}]
let passed=0
function check(name, fn){fn();passed++;console.log('PASS',name)}
function noOverlap(scene){
  for(let i=0;i<scene.nodes.length;i++)for(const b of scene.nodes.slice(i+1)){
    const a=scene.nodes[i]
    assert.ok(a.x+NODE_W<=b.x || b.x+NODE_W<=a.x || a.y+NODE_H<=b.y || b.y+NODE_H<=a.y, `cards ${a.id}/${b.id}`)
  }
}
function noCrossCard(scene){
  for(const e of scene.edges)for(let i=1;i<e.points.length;i++)for(const n of scene.nodes){
    const a=e.points[i-1],b=e.points[i]
    const hit=a.x===b.x ? a.x>n.x+.1 && a.x<n.x+NODE_W-.1 && Math.max(a.y,b.y)>n.y+.1 && Math.min(a.y,b.y)<n.y+NODE_H-.1
      : a.y>n.y+.1 && a.y<n.y+NODE_H-.1 && Math.max(a.x,b.x)>n.x+.1 && Math.min(a.x,b.x)<n.x+NODE_W-.1
    assert.ok(!hit,`${e.id} crosses card ${n.id}`)
  }
}
for(const kind of ['tree','side','spine','ring','fan'])for(const orientation of ['vertical','horizontal']){
  const scene=buildScene(kind,nodes,1,orientation,false,{marriages,parentchild:pc})
  check(`${kind}/${orientation} 全员唯一、无重叠、连线不穿卡`,()=>{
    assert.deepEqual(scene.nodes.map(n=>n.id).sort(),nodes.map(n=>n.id).sort());noOverlap(scene);noCrossCard(scene)
    assert.equal(scene.edges.filter(e=>e.kind==='marriage').length,2)
    assert.equal(scene.edges.filter(e=>e.kind==='parentchild').length,4)
    assert.ok(scene.edges.every(e=>e.points.length>=2))
    assert.ok(scene.edges.every(e=>e.points.every(p=>p.x>=scene.bounds.minX && p.x<=scene.bounds.maxX && p.y>=scene.bounds.minY && p.y<=scene.bounds.maxY)))
  })
  if(['tree','side','spine'].includes(kind))check(`${kind}/${orientation} 配偶同世代分区、双亲分组与层级`,()=>{
    const pos=new Map(scene.nodes.map(n=>[n.id,n]));const rank=kind!=='spine' && orientation==='vertical'?'y':'x'
    {assert.ok(scene.areas.some(a=>a.memberIds.includes(2)&&a.memberIds.includes(3)));assert.ok(scene.areas.some(a=>a.memberIds.includes(4)&&a.memberIds.includes(6)))}
    assert.ok(pos.get(3)[rank]>pos.get(2)[rank]);assert.ok(pos.get(6)[rank]>pos.get(4)[rank])
    assert.ok(pos.get(1)[rank]<pos.get(2)[rank] && pos.get(2)[rank]<pos.get(4)[rank] && pos.get(4)[rank]<pos.get(7)[rank])
    assert.deepEqual(scene.families.find(f=>f.parents.includes(2) && f.parents.includes(3)).children.map(x=>x.id).sort(),[4,5])
  })
  check(`${kind}/${orientation} 直系集合与悬空线`,()=>{
    const direct=buildScene(kind,nodes,4,orientation,true,{marriages,parentchild:pc});const ids=new Set(direct.nodes.map(n=>n.id))
    assert.deepEqual([...ids].sort(),filterLine(nodes,4,true).map(n=>n.id).sort())
    assert.ok(direct.edges.every(e=>e.memberIds.every(id=>ids.has(id))))
  })
}
const remarried=[node(10,1,1,[],[13,14],[11,12]),node(11,1,3,[],[13],[10]),node(12,1,3,[],[14],[10]),node(13,2,1,[10,11]),node(14,2,2,[10,12])]
check('再婚不串母亲，成员只绘制一次',()=>{
  const scene=buildScene('tree',remarried,10,'vertical',false,{marriages:[{id:3,spouse1_id:10,spouse2_id:11,marriage_order:1},{id:4,spouse1_id:10,spouse2_id:12,marriage_order:2}]})
  assert.equal(scene.nodes.length,5);noOverlap(scene);noCrossCard(scene)
  assert.deepEqual(scene.families.find(f=>f.parents.includes(11)).children.map(c=>c.id),[13]);assert.deepEqual(scene.families.find(f=>f.parents.includes(12)).children.map(c=>c.id),[14])
})
for(const kind of ['tree','side','spine','ring','fan'])for(const orientation of ['vertical','horizontal'])check(`${kind}/${orientation} 再婚分通道、父母语义与子女箭头`,()=>{
  const scene=buildScene(kind,remarried,10,orientation,false,{marriages:[{id:3,spouse1_id:10,spouse2_id:11,marriage_order:1},{id:4,spouse1_id:10,spouse2_id:12,marriage_order:2}]})
  noOverlap(scene);noCrossCard(scene)
  const first=scene.edges.find(e=>e.targetId===13),second=scene.edges.find(e=>e.targetId===14)
  assert.equal(first.sourceId,11);assert.equal(second.sourceId,12)
  assert.deepEqual(first.memberIds,[10,11,13]);assert.deepEqual(second.memberIds,[10,12,14])
  assert.ok(scene.edges.every(e=>e.arrow===(e.kind==='parentchild')))
  if(['tree','side','spine'].includes(kind)){
    const a=scene.nodes.find(n=>n.id===11),b=scene.nodes.find(n=>n.id===12),x=scene.nodes.find(n=>n.id===13),y=scene.nodes.find(n=>n.id===14)
    const horizontal=kind==='spine'||orientation==='horizontal'
    assert.ok((horizontal?a.y:a.x)<(horizontal?b.y:b.x))
    assert.ok((horizontal?x.y:x.x)<(horizontal?y.y:y.x))
  }
})
check('直系延展主链对齐，保留配偶与旁支',()=>{
  const scene=buildScene('spine',nodes,1,'horizontal',false,{marriages,parentchild:pc}),pos=new Map(scene.nodes.map(n=>[n.id,n]))
  for(const id of [1,2,4,7])assert.equal(pos.get(id).y,0)
  assert.equal(scene.nodes.length,7)
})
check('共同父母不能伪造婚姻，单亲不补造成员',()=>{
  const scene=buildScene('tree',nodes.map(n=>({...n,spouses:[]})),1,'vertical',false,{marriages:[],parentchild:pc})
  assert.equal(scene.edges.filter(e=>e.kind==='marriage').length,0)
  assert.ok(scene.edges.some(e=>e.kind==='coparent'));assert.equal(scene.nodes.length,7)
})
check('收养关系保留类型，多组父母不混成一组',()=>{
  const ns=[node(20,1,1,[],[24]),node(21,1,3,[],[24]),node(22,1,1,[],[24]),node(23,1,3,[],[24]),node(24,2,1,[20,21,22,23])]
  const scene=buildScene('tree',ns,20,'vertical',false,{marriages:[],parentchild:ns[4].parents.map((p,i)=>({id:i,parent_id:p,child_id:24,type:i<2?1:3}))})
  assert.deepEqual(scene.families.filter(f=>f.children.length).map(f=>f.parents).sort(),[[20,21],[22,23]])
  assert.ok(scene.edges.some(e=>e.kind==='parentchild' && e.label.includes('收养')));noCrossCard(scene)
})
check('并排式真实响应方向，主人物不改变祖先位置',()=>{
  const v=layoutOf('side',nodes,1,'vertical',false),h=layoutOf('side',nodes,7,'horizontal',false)
  assert.notDeepEqual(v.map(n=>[n.x,n.y]),h.map(n=>[n.x,n.y]))
  assert.ok(h.find(n=>n.id===1).x<h.find(n=>n.id===7).x)
})
check('矛盾数据保留成员并提示，不修改原对象',()=>{
  const ns=structuredClone(nodes);ns[2].generation=8;const before=JSON.stringify(ns)
  const scene=buildScene('tree',ns,1,'vertical',false,{marriages,parentchild:pc})
  assert.equal(scene.nodes.length,7);assert.ok(scene.warnings.length);assert.equal(JSON.stringify(ns),before);noCrossCard(scene)
})
check('男女统一排行优先于生日，未知排行不编造',()=>{
  const ns=[node(1,1,1,[],[2,3]),node(2,2,2,[1]),node(3,2,1,[1])]
  ns[1].birth_date='2005-01-01';ns[2].birth_date='2000-01-01'
  const parentchild=[{id:1,parent_id:1,child_id:2,type:1,child_order:1},{id:2,parent_id:1,child_id:3,type:1,child_order:2}]
  let scene=buildScene('tree',ns,1,'vertical',false,{parentchild})
  assert.ok(scene.nodes.find(n=>n.id===2).x<scene.nodes.find(n=>n.id===3).x)
  assert.ok(scene.edges.some(e=>e.label==='排行 1'))
  scene=buildScene('tree',ns,1,'vertical',false,{parentchild:parentchild.map(e=>({...e,child_order:null}))})
  assert.ok(scene.nodes.find(n=>n.id===3).x<scene.nodes.find(n=>n.id===2).x)
  assert.ok(scene.edges.every(e=>!e.label.includes('排行')))
})
const extended=[node(1,1,1,[],[4,5,6],[2,3]),node(2,1,3,[],[4,5],[1]),node(3,1,3,[],[6],[1]),
  node(4,2,2,[1,2],[9],[7,8]),node(5,2,1,[1,2]),node(6,2,1,[1,3]),node(7,2,4,[],[9],[4]),node(8,2,4,[],[],[4]),node(9,3,1,[4,7])]
const extendedMarriages=[{id:1,spouse1_id:1,spouse2_id:2,marriage_order:1},{id:2,spouse1_id:1,spouse2_id:3,marriage_order:2},
  {id:3,spouse1_id:4,spouse2_id:7,marriage_order:1},{id:4,spouse1_id:4,spouse2_id:8,marriage_order:2}]
for(const kind of ['tree','side','spine','ring','fan'])check(`${kind} 女性主成员再婚、无子女婚姻和后代再婚`,()=>{
  const scene=buildScene(kind,extended,1,'horizontal',false,{marriages:extendedMarriages})
  assert.equal(scene.nodes.length,9);assert.equal(scene.edges.filter(e=>e.kind==='marriage').length,4)
  assert.equal(scene.edges.find(e=>e.targetId===9).sourceId,7)
  assert.deepEqual(scene.edges.find(e=>e.targetId===9).memberIds,[4,7,9]);noOverlap(scene);noCrossCard(scene)
  for(const e of scene.edges.filter(e=>e.arrow)){
    const target=scene.nodes.find(n=>n.id===e.targetId),last=e.points[e.points.length-1],prev=e.points[e.points.length-2]
    assert.ok((last.x===target.x&&prev.x<last.x)||(last.x===target.x+NODE_W&&prev.x>last.x)
      ||(last.y===target.y&&prev.y<last.y)||(last.y===target.y+NODE_H&&prev.y>last.y))
  }
})
check('三段婚姻各自保留子女通道',()=>{
  const ns=[node(30,1,1,[],[34,35,36],[31,32,33]),...Array.from({length:3},(_,i)=>node(31+i,1,3,[],[34+i],[30])),...Array.from({length:3},(_,i)=>node(34+i,2,1,[30,31+i]))]
  for(const o of ['horizontal','vertical']){
    const scene=buildScene('tree',ns,30,o,false,{marriages:[1,2,3].map((order,i)=>({id:order,spouse1_id:30,spouse2_id:31+i,marriage_order:order}))})
    for(let i=0;i<3;i++)assert.equal(scene.edges.find(e=>e.targetId===34+i).sourceId,31+i)
    noOverlap(scene);noCrossCard(scene)
  }
})
for(const kind of ['tree','side','spine','ring','fan'])for(const orientation of ['vertical','horizontal'])check(`${kind}/${orientation} 再婚同时存在仅登记一方的收养关系`,()=>{
  const ns=[...remarried.map(n=>({...n,children:[...n.children]})),node(15,2,2,[10])];ns[0].children.push(15)
  const parentchild=ns.flatMap(n=>n.children.map(child_id=>({id:n.id*100+child_id,parent_id:n.id,child_id,type:child_id===15?3:1})))
  const scene=buildScene(kind,ns,10,orientation,false,{parentchild})
  assert.equal(scene.nodes.length,6);noOverlap(scene);noCrossCard(scene)
  const edge=scene.edges.find(e=>e.targetId===15);assert.equal(edge.sourceId,10);assert.deepEqual(edge.memberIds,[10,15]);assert.equal(edge.special,true)
})
check('重复渲染稳定且输入数据不变',()=>{
  const before=JSON.stringify(extended),a=buildScene('tree',extended,1,'horizontal',false,{marriages:extendedMarriages}),b=buildScene('tree',extended,1,'horizontal',false,{marriages:extendedMarriages})
  assert.deepEqual(a,b);assert.equal(JSON.stringify(extended),before)
})
check('独立成员不遗漏，大谱不重叠',()=>{
  const ns=Array.from({length:300},(_,i)=>node(i+1000,1,1))
  const scene=buildScene('tree',ns,1000,'vertical',false);assert.equal(scene.nodes.length,300);noOverlap(scene)
})
console.log(`布局检查：${passed} 项通过`)

for(const kind of ['tree','side','spine','ring','fan'])for(const orientation of ['vertical','horizontal'])check(`${kind}/${orientation} 关系标签避开人员卡片`,()=>{
  const scene=buildScene(kind,remarried,10,orientation,false,{marriages:[{id:3,spouse1_id:10,spouse2_id:11,marriage_order:1},{id:4,spouse1_id:10,spouse2_id:12,marriage_order:2}]})
  for(const e of scene.edges.filter(e=>e.label)){
    const at=e.labelAt,w=Math.min(24,e.label.length)*9+8,r={x:at.x-w/2,y:at.y-12,width:w,height:16}
    assert.ok(scene.nodes.every(n=>r.x+r.width<=n.x || r.x>=n.x+NODE_W || r.y+r.height<=n.y || r.y>=n.y+NODE_H),e.id)
  }
})
console.log(`最终布局检查：${passed} 项通过`)

check('横向树从对应妻子、女婿右侧接出，下一代位于家庭分区右侧',()=>{
  const scene=buildScene('tree',extended,1,'horizontal',false,{marriages:extendedMarriages}),pos=new Map(scene.nodes.map(n=>[n.id,n]))
  for(const [childId,spouseId] of [[4,2],[5,2],[6,3],[9,7]]){
    const child=pos.get(childId),spouse=pos.get(spouseId),edge=scene.edges.find(e=>e.targetId===childId)
    assert.equal(edge.sourceId,spouseId)
    assert.deepEqual(edge.points[0],{x:spouse.x+NODE_W,y:spouse.y+NODE_H/2})
    assert.ok(edge.points[1].x>edge.points[0].x)
    const area=scene.areas.find(a=>a.memberIds.includes(spouseId))
    assert.ok(area);assert.ok(child.x>area.x+area.width)
  }
  noOverlap(scene);noCrossCard(scene)
})
check('仅有父亲记录时不能按唯一配偶虚构母亲关系',()=>{
  const ns=[node(1,18,1,[],[3],[2]),node(2,18,3,[],[],[1]),node(3,19,1,[1])]
  const scene=buildScene('tree',ns,1,'horizontal',false)
  const edge=scene.edges.find(e=>e.targetId===3)
  assert.equal(edge.sourceId,1);assert.deepEqual(edge.memberIds,[1,3])
  assert.ok(!scene.families.some(f=>f.parents.includes(2)&&f.children.some(c=>c.id===3)))
})
console.log(`本轮布局检查：${passed} 项通过`)

const screenshotFamily=[node(101,17,1,[],[102,104]),node(102,18,1,[101],[],[103]),node(103,18,3,[],[],[102]),
  node(104,18,1,[101],[106,107,108,109],[105]),node(105,18,3,[],[106,107,108,109],[104]),
  node(106,19,1,[104,105]),node(107,19,1,[104,105]),node(108,19,2,[104,105],[111],[110]),
  node(109,19,2,[104,105]),node(110,19,4,[],[111],[108]),node(111,20,5,[108,110])]
const screenshotRelations={marriages:[{id:21,spouse1_id:102,spouse2_id:103,marriage_order:1},
  {id:22,spouse1_id:104,spouse2_id:105,marriage_order:1},{id:23,spouse1_id:108,spouse2_id:110,marriage_order:1}]}
check('截图横向：恢复夫妻框，所有亲子线从配偶右侧接出',()=>{
  const scene=buildScene('tree',screenshotFamily,101,'horizontal',false,screenshotRelations)
  const pos=new Map(scene.nodes.map(n=>[n.id,n]))
  for(const [a,b] of [[102,103],[104,105],[108,110]])assert.equal(pos.get(a).y,pos.get(b).y,'夫妻不应被子孙数量拉开')
  const routes=[106,107,108,109].map(id=>scene.edges.find(e=>e.targetId===id))
  for(const edge of routes){
    const target=pos.get(edge.targetId),end=edge.points.at(-1),previous=edge.points.at(-2)
    assert.deepEqual(end,{x:target.x,y:target.y+NODE_H/2})
    assert.ok(previous.x<end.x && previous.y===end.y,'多子女箭头应从左侧进入，避免绕回顶部')
    assert.deepEqual(edge.points[0],{x:pos.get(105).x+NODE_W,y:pos.get(105).y+NODE_H/2})
    assert.ok(edge.points[1].x>edge.points[0].x)
  }
  const single=scene.edges.find(e=>e.targetId===111),target=pos.get(111)
  assert.deepEqual(single.points.at(-1),{x:target.x,y:target.y+NODE_H/2})
  assert.deepEqual(single.points[0],{x:pos.get(110).x+NODE_W,y:pos.get(110).y+NODE_H/2})
  assert.equal(scene.areas.length,3)
  for(const area of scene.areas)for(const n of scene.nodes){
    if(area.memberIds.includes(n.id))continue
    assert.ok(n.x+NODE_W<=area.x || n.x>=area.x+area.width || n.y+NODE_H<=area.y || n.y>=area.y+area.height,'夫妻框不能包含子女或其他家庭')
  }
  noOverlap(scene);noCrossCard(scene)
})
console.log(`横向连线回归：${passed} 项通过`)
