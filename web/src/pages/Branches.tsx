import { useEffect, useState } from 'react'
import {
  Button, Card, Form, Input, Modal, Pagination, Popconfirm, Segmented, Select, Space, Table, Tag, message,
} from 'antd'
import { PlusOutlined, TeamOutlined } from '@ant-design/icons'
import { api } from '../api'
import { useStore } from '../store'
import MemberPicker from '../components/MemberPicker'
import ColumnSettings, { useColumnSettings } from '../components/ColumnSettings'
import { PERSON_TYPES } from '../constants'

interface Row {
  id: number
  name: string
  parent_id: number | null
  hall_name: string
  generation_chars: string
  origin_place: string
  description: string
  person_count: number
}

interface MemberRow {
  id: number
  name: string
  generation: number
  type: number
  branch_name?: string
}

export default function Branches() {
  const { user, familyId } = useStore()
  const fam = user?.families.find((f) => f.id === familyId)
  const writeable = !!fam && (fam.role === 'admin' || !!user?.is_superuser)
  const [rows, setRows] = useState<Row[]>([])
  const [allBranches, setAllBranches] = useState<Row[]>([])
  const [page, setPage] = useState(1)
  const [total, setTotal] = useState(0)
  const size = user?.page_size || 50
  const [view, setView] = useState<'table' | 'card'>(
    () => (localStorage.getItem('fts_branch_view') === 'card' ? 'card' : 'table'))
  const cols = useColumnSettings<any>('fts_branch_cols')
  const columnMeta = [
    { key: 'name', title: '分支名称' },
    { key: 'parent', title: '上级分支' },
    { key: 'hall_name', title: '堂号' },
    { key: 'generation_chars', title: '字辈' },
    { key: 'origin_place', title: '发源地' },
    { key: 'person_count', title: '人数' },
    { key: 'actions', title: '操作' },
  ]
  const [open, setOpen] = useState(false)
  const [editing, setEditing] = useState<Row | null>(null)
  const [form] = Form.useForm()
  const [memberFor, setMemberFor] = useState<Row | null>(null)
  const [memberRows, setMemberRows] = useState<MemberRow[]>([])
  const [memberPage, setMemberPage] = useState(1)
  const [memberTotal, setMemberTotal] = useState(0)
  const [addIds, setAddIds] = useState<number[]>([])
  const [removeIds, setRemoveIds] = useState<number[]>([])

  const load = async () => {
    if (!familyId) return
    try {
      const d = await api.get(`/api/families/${familyId}/branches?page=${page}&size=${size}`)
      setRows(d.items)
      setTotal(d.total)
      setAllBranches(await api.get(`/api/families/${familyId}/branches?all=1`))
    } catch (e: any) {
      message.error(e.message)
    }
  }

  useEffect(() => {
    load()
  }, [familyId, page, size])

  const loadMembers = async (branchId: number, p: number) => {
    try {
      const d = await api.get(
        `/api/families/${familyId}/persons?branch_id=${branchId}&page=${p}&size=${size}`)
      setMemberRows(d.items)
      setMemberTotal(d.total)
      if (!d.items.length && p > 1) setMemberPage(Math.max(1, Math.ceil(d.total / size)))
    } catch (e: any) {
      message.error(e.message)
    }
  }

  useEffect(() => {
    if (memberFor) loadMembers(memberFor.id, memberPage)
  }, [memberFor?.id, memberPage])

  const openEdit = (row: Row | null) => {
    setEditing(row)
    if (row) form.setFieldsValue(row)
    else form.resetFields()
    if (!row) form.setFieldValue('person_ids', [])
    setOpen(true)
  }

  const save = async () => {
    const v = await form.validateFields()
    try {
      if (editing) await api.put(`/api/families/${familyId}/branches/${editing.id}`, v)
      else await api.post(`/api/families/${familyId}/branches`, v)
      message.success('已保存')
      setOpen(false)
      load()
    } catch (e: any) {
      message.error(e.message)
    }
  }

  const openMembers = (row: Row) => {
    setMemberFor(row)
    setMemberPage(1)
    setAddIds([])
    setRemoveIds([])
  }

  const refreshMembers = async () => {
    if (!memberFor) return
    if (memberRows.length === 1 && memberPage > 1) {
      setMemberPage(memberPage - 1)
      load()
      return
    }
    await loadMembers(memberFor.id, memberPage)
    load()
  }

  const addMember = async () => {
    if (!memberFor || !addIds.length) {
      message.warning('请选择要加入的成员')
      return
    }
    try {
      await api.post(`/api/families/${familyId}/branches/${memberFor.id}/members`,
        { add_ids: addIds })
      setAddIds([])
      setRemoveIds([])
      message.success('已加入分支')
      await refreshMembers()
    } catch (e: any) {
      message.error(e.message)
    }
  }

  const removeMember = async (id: number) => {
    if (!memberFor) return
    try {
      await api.post(`/api/families/${familyId}/branches/${memberFor.id}/members`,
        { remove_ids: [id] })
      message.success('已移出分支')
      await refreshMembers()
    } catch (e: any) {
      message.error(e.message)
    }
  }

  return (
    <Card
      title="分支房系"
      extra={
        writeable && (
          <Button type="primary" icon={<PlusOutlined />} onClick={() => openEdit(null)}>
            新建分支
          </Button>
        )
      }
    >
      <Space wrap style={{ marginBottom: 12 }}>
        <ColumnSettings columns={columnMeta} hidden={cols.hidden} onToggle={cols.toggle} />
        <Segmented
          size="small"
          value={view}
          onChange={(v) => {
            const next = v as 'table' | 'card'
            setView(next)
            localStorage.setItem('fts_branch_view', next)
          }}
          options={[{ value: 'table', label: '列表' }, { value: 'card', label: '卡片' }]}
        />
      </Space>
      {view === 'table' ? (
      <Table
        rowKey="id"
        dataSource={rows}
        pagination={{ current: page, pageSize: size, total, onChange: setPage, showSizeChanger: false }}
        scroll={{ x: 900 }}
        columns={cols.visible([
          { key: 'name', title: '分支名称', dataIndex: 'name', width: 140 },
          {
            key: 'parent',
            title: '上级分支',
            width: 120,
            render: (_: any, r: Row) => allBranches.find((b) => b.id === r.parent_id)?.name || '-',
          },
          { key: 'hall_name', title: '堂号', dataIndex: 'hall_name', width: 110 },
          { key: 'generation_chars', title: '字辈', dataIndex: 'generation_chars', width: 140 },
          { key: 'origin_place', title: '发源地', dataIndex: 'origin_place', width: 120 },
          { key: 'person_count', title: '人数', dataIndex: 'person_count', width: 80 },
          {
            key: 'actions',
            title: '操作',
            width: 190,
            fixed: 'right',
            render: (_: any, r: Row) =>
              writeable ? (
                <Space size={4}>
                  <Button size="small" icon={<TeamOutlined />} onClick={() => openMembers(r)}>
                    成员
                  </Button>
                  <Button size="small" onClick={() => openEdit(r)}>编辑</Button>
                  <Popconfirm
                    title="删除后其成员将归为未分配，确认删除？"
                    onConfirm={async () => {
                      await api.del(`/api/families/${familyId}/branches/${r.id}`)
                      load()
                    }}
                  >
                    <Button size="small" danger>删除</Button>
                  </Popconfirm>
                </Space>
              ) : null,
          },
        ])}
      />
      ) : (
        <>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill,minmax(280px,1fr))', gap: 12 }}>
            {rows.map((r) => (
              <Card key={r.id} size="small" title={r.name}
                extra={<Tag color="blue">{r.person_count} 人</Tag>}>
                <Space direction="vertical" size={4} style={{ width: '100%' }}>
                  <span style={{ fontSize: 12, color: '#888' }}>
                    上级：{allBranches.find((b) => b.id === r.parent_id)?.name || '-'}
                  </span>
                  <span style={{ fontSize: 12, color: '#888' }}>
                    堂号：{r.hall_name || '-'}　字辈：{r.generation_chars || '-'}
                  </span>
                  <span style={{ fontSize: 12, color: '#888' }}>发源地：{r.origin_place || '-'}</span>
                  <span style={{ fontSize: 13 }}>{r.description || '无简介'}</span>
                  {writeable && (
                    <Space wrap size={4}>
                      <Button size="small" icon={<TeamOutlined />} onClick={() => openMembers(r)}>成员</Button>
                      <Button size="small" onClick={() => openEdit(r)}>编辑</Button>
                      <Popconfirm title="删除后其成员将归为未分配，确认删除？"
                        onConfirm={async () => {
                          await api.del(`/api/families/${familyId}/branches/${r.id}`)
                          load()
                        }}>
                        <Button size="small" danger>删除</Button>
                      </Popconfirm>
                    </Space>
                  )}
                </Space>
              </Card>
            ))}
          </div>
          {total > size && (
            <Pagination simple current={page} pageSize={size} total={total}
              onChange={setPage} style={{ textAlign: 'center', marginTop: 12 }} />
          )}
        </>
      )}

      <Modal
        open={open}
        title={editing ? '编辑分支' : '新建分支'}
        onCancel={() => setOpen(false)}
        onOk={save}
        width={850}
        destroyOnClose
      >
        <Form form={form} layout="vertical">
          <Space size={12} wrap>
            <Form.Item name="name" label="分支名称" rules={[{ required: true }]}>
              <Input />
            </Form.Item>
            <Form.Item name="parent_id" label="上级分支">
              <Select
                allowClear
                style={{ width: 160 }}
                options={allBranches
                  .filter((b) => !editing || b.id !== editing.id)
                  .map((b) => ({ value: b.id, label: b.name }))}
              />
            </Form.Item>
            <Form.Item name="hall_name" label="堂号">
              <Input />
            </Form.Item>
            <Form.Item name="generation_chars" label="字辈">
              <Input placeholder="如：木火土金水" />
            </Form.Item>
            <Form.Item name="origin_place" label="发源地">
              <Input />
            </Form.Item>
          </Space>
          <Form.Item name="description" label="家族训 / 简介">
            <Input.TextArea rows={2} />
          </Form.Item>
          {!editing && <Form.Item name="person_ids" label="初始成员（可筛选、跨页勾选）">
            <MemberPicker />
          </Form.Item>}
        </Form>
      </Modal>

      <Modal
        open={!!memberFor}
        title={`分支成员 - ${memberFor?.name}`}
        onCancel={() => setMemberFor(null)}
        footer={null}
        width={720}
        destroyOnClose
      >
        <Card size="small" title="批量加入成员" style={{ marginBottom: 16 }}>
          <MemberPicker key={memberFor?.id} value={addIds} onChange={setAddIds} />
          <Button type="primary" onClick={addMember} disabled={!addIds.length}>将所选 {addIds.length} 人加入分支</Button>
        </Card>
        <Space style={{ marginBottom: 8 }}>
          <span>当前分支成员</span>
          <Popconfirm title={`确认将所选 ${removeIds.length} 人移出分支？`} onConfirm={async () => {
            try {
              await api.post(`/api/families/${familyId}/branches/${memberFor!.id}/members`, { remove_ids: removeIds })
              setRemoveIds([])
              await refreshMembers()
            } catch (e: any) { message.error(e.message) }
          }}>
            <Button danger disabled={!removeIds.length}>批量移出所选成员</Button>
          </Popconfirm>
        </Space>
        <Table
          rowKey="id"
          size="small"
          dataSource={memberRows}
          rowSelection={{ selectedRowKeys: removeIds, preserveSelectedRowKeys: true, onChange: ids => setRemoveIds(ids.map(Number)) }}
          pagination={{
            current: memberPage,
            pageSize: size,
            total: memberTotal,
            onChange: setMemberPage,
            showSizeChanger: false,
          }}
          columns={[
            { title: '姓名', dataIndex: 'name' },
            { title: '世代', dataIndex: 'generation', width: 80, render: (g: number) => `第${g}世` },
            { title: '类型', dataIndex: 'type', width: 100, render: (t: number) => PERSON_TYPES[t] },
            {
              title: '操作',
              width: 90,
              render: (_, r: MemberRow) => (
                <Popconfirm title="确认移出该分支？" onConfirm={() => removeMember(r.id)}>
                  <Button size="small" danger>移出</Button>
                </Popconfirm>
              ),
            },
          ]}
        />
      </Modal>
    </Card>
  )
}
