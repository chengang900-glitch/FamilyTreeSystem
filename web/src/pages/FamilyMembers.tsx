import { useEffect, useRef, useState } from 'react'
import { Button, Card, Input, Popconfirm, Select, Space, Table, Tag, message } from 'antd'
import { api } from '../api'
import { useStore } from '../store'

export default function FamilyMembers() {
  const { user, familyId } = useStore()
  const fam = user?.families.find((f) => f.id === familyId)
  const writeable = !!fam && (fam.role === 'admin' || !!user?.is_superuser)
  // 授予「家谱管理员」只允许超管操作（后端同样校验）
  const canGrantAdmin = !!user?.is_superuser
  const [rows, setRows] = useState<any[]>([])
  const [candidates, setCandidates] = useState<any[]>([])
  const [kw, setKw] = useState('')
  const [pick, setPick] = useState<number | undefined>()
  const [role, setRole] = useState<'admin' | 'member'>('member')
  const timer = useRef<number | undefined>(undefined)

  const load = async () => {
    if (!familyId) return
    setRows(await api.get(`/api/families/${familyId}/members`))
  }

  useEffect(() => {
    load()
  }, [familyId])

  useEffect(() => () => window.clearTimeout(timer.current), [])

  const search = (v: string) => {
    setKw(v)
    window.clearTimeout(timer.current)
    if (!v) {
      setCandidates([])
      return
    }
    // 防抖：输入停顿 300ms 再请求，避免逐字触发
    timer.current = window.setTimeout(async () => {
      try {
        const r = await api.get(
          `/api/families/${familyId}/members/search?keyword=${encodeURIComponent(v)}`)
        setCandidates(r)
      } catch (e: any) {
        message.error(e.message)
      }
    }, 300)
  }

  const add = async () => {
    if (!pick) return
    try {
      await api.post(`/api/families/${familyId}/members`, { user_id: pick, role })
      message.success('已加入')
      setPick(undefined)
      setCandidates([])
      setKw('')
      load()
    } catch (e: any) {
      message.error(e.message)
    }
  }

  const columns = [
    { title: '账号', dataIndex: 'username', width: 140 },
    { title: '姓名', dataIndex: 'real_name', width: 120 },
    ...(writeable ? [{ title: '手机', dataIndex: 'phone', width: 140 }] : []),
    {
      title: '角色',
      width: 130,
      render: (_: any, r: any) => (
        <Tag color={r.role === 'admin' ? 'orange' : 'green'}>
          {r.role === 'admin' ? '家谱管理员' : '家族普通用户'}
        </Tag>
      ),
    },
    {
      title: '操作',
      width: 100,
      render: (_: any, r: any) =>
        writeable ? (
          <Popconfirm
            title="确认移出该家谱？"
            onConfirm={async () => {
              try {
                await api.del(`/api/families/${familyId}/members/${r.id}`)
                load()
              } catch (e: any) {
                message.error(e.message)
              }
            }}
          >
            <Button size="small" danger>移出</Button>
          </Popconfirm>
        ) : null,
    },
  ]

  return (
    <Card title="家谱成员（登录账号）">
      {!writeable && (
        <div style={{ padding: '24px 0', color: '#888' }}>
          仅家谱管理员可查看与维护成员名单。
        </div>
      )}
      {writeable && (
        <Space wrap style={{ marginBottom: 12 }}>
          <Input.Search
            placeholder="搜索账号/姓名/手机号"
            value={kw}
            onChange={(e) => search(e.target.value)}
            style={{ width: 240 }}
          />
          {canGrantAdmin && (
            <Select
              value={role}
              onChange={setRole}
              style={{ width: 130 }}
              options={[
                { value: 'member', label: '家族普通用户' },
                { value: 'admin', label: '家谱管理员' },
              ]}
            />
          )}
          <Select
            style={{ width: 220 }}
            placeholder="选择用户"
            value={pick}
            onChange={setPick}
            options={candidates.map((u) => ({
              value: u.id,
              label: `${u.username}${u.real_name ? '（' + u.real_name + '）' : ''}`,
            }))}
          />
          <Button type="primary" onClick={add} disabled={!pick}>加入家谱</Button>
        </Space>
      )}
      {writeable && (
        <Table rowKey="id" dataSource={rows} columns={columns as any} />
      )}
    </Card>
  )
}
