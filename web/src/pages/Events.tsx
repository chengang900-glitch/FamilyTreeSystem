import { useEffect, useState } from 'react'
import {
  Button, Card, Drawer, Form, Input, Modal, Pagination, Popconfirm, Segmented, Select, Space, Table, Tag, message,
} from 'antd'
import { PlusOutlined } from '@ant-design/icons'
import { api } from '../api'
import { useStore } from '../store'
import PersonSelect from '../components/PersonSelect'
import DateInput from '../components/DateInput'
import ColumnSettings, { useColumnSettings } from '../components/ColumnSettings'
import { EVENT_TYPES } from '../constants'

interface Row {
  id: number
  name: string
  time: string
  place: string
  type: number
  description: string
  branch_id: number | null
  person_count: number
}

export default function Events() {
  const { user, familyId } = useStore()
  const fam = user?.families.find((f) => f.id === familyId)
  const writeable = !!fam && (fam.role === 'admin' || !!user?.is_superuser)
  const [rows, setRows] = useState<Row[]>([])
  const [branches, setBranches] = useState<any[]>([])
  const [page, setPage] = useState(1)
  const [total, setTotal] = useState(0)
  const size = user?.page_size || 50
  const [view, setView] = useState<'table' | 'card'>(
    () => (localStorage.getItem('fts_event_view') === 'card' ? 'card' : 'table'))
  const cols = useColumnSettings<any>('fts_event_cols')
  const columnMeta = [
    { key: 'name', title: '事件名称' },
    { key: 'time', title: '时间' },
    { key: 'place', title: '地点' },
    { key: 'type', title: '类型' },
    { key: 'branch', title: '关联分支' },
    { key: 'description', title: '描述' },
    { key: 'persons', title: '参与人' },
    { key: 'actions', title: '操作' },
  ]
  const [open, setOpen] = useState(false)
  const [editing, setEditing] = useState<Row | null>(null)
  const [form] = Form.useForm()
  const [personsFor, setPersonsFor] = useState<Row | null>(null)
  const [participants, setParticipants] = useState<any[]>([])
  const [addForm] = Form.useForm()

  const load = async () => {
    if (!familyId) return
    try {
      const d = await api.get(`/api/families/${familyId}/events?page=${page}&size=${size}`)
      setRows(d.items)
      setTotal(d.total)
      setBranches(await api.get(`/api/families/${familyId}/branches`))
    } catch (e: any) {
      message.error(e.message)
    }
  }

  useEffect(() => {
    load()
  }, [familyId, page, size])

  const save = async () => {
    const v = await form.validateFields()
    try {
      if (editing) await api.put(`/api/families/${familyId}/events/${editing.id}`, v)
      else await api.post(`/api/families/${familyId}/events`, v)
      message.success('已保存')
      setOpen(false)
      load()
    } catch (e: any) {
      message.error(e.message)
    }
  }

  const openPersons = async (row: Row) => {
    setPersonsFor(row)
    setParticipants(await api.get(`/api/families/${familyId}/events/${row.id}/persons`))
  }

  const addParticipant = async () => {
    const v = await addForm.validateFields()
    try {
      await api.post(`/api/families/${familyId}/events/${personsFor!.id}/persons`, v)
      setParticipants(await api.get(`/api/families/${familyId}/events/${personsFor!.id}/persons`))
      addForm.resetFields()
      load()
    } catch (e: any) {
      message.error(e.message)
    }
  }

  return (
    <Card
      title="家族事件"
      extra={
        writeable && (
          <Button
            type="primary"
            icon={<PlusOutlined />}
            onClick={() => {
              setEditing(null)
              form.resetFields()
              form.setFieldsValue({ type: 1 })
              setOpen(true)
            }}
          >
            添加事件
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
            localStorage.setItem('fts_event_view', next)
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
          { key: 'name', title: '事件名称', dataIndex: 'name', width: 160 },
          { key: 'time', title: '时间', dataIndex: 'time', width: 130 },
          { key: 'place', title: '地点', dataIndex: 'place', width: 140 },
          {
            key: 'type',
            title: '类型',
            dataIndex: 'type',
            width: 100,
            render: (t: number) => <Tag>{EVENT_TYPES[t]}</Tag>,
          },
          {
            key: 'branch',
            title: '关联分支',
            width: 110,
            render: (_: any, r: Row) => branches.find((b) => b.id === r.branch_id)?.name || '-',
          },
          { key: 'description', title: '描述', dataIndex: 'description' },
          {
            key: 'persons',
            title: '参与人',
            width: 90,
            render: (_: any, r: Row) => (
              <Button size="small" onClick={() => openPersons(r)}>{r.person_count} 人</Button>
            ),
          },
          {
            key: 'actions',
            title: '操作',
            width: 130,
            fixed: 'right',
            render: (_: any, r: Row) =>
              writeable ? (
                <Space size={4}>
                  <Button
                    size="small"
                    onClick={() => {
                      setEditing(r)
                      form.setFieldsValue(r)
                      setOpen(true)
                    }}
                  >
                    编辑
                  </Button>
                  <Popconfirm
                    title="确认删除该事件？"
                    onConfirm={async () => {
                      await api.del(`/api/families/${familyId}/events/${r.id}`)
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
                extra={<Tag>{EVENT_TYPES[r.type]}</Tag>}>
                <Space direction="vertical" size={4} style={{ width: '100%' }}>
                  <span style={{ fontSize: 12, color: '#888' }}>
                    {r.time || '时间不详'} · {r.place || '地点不详'}
                  </span>
                  <span style={{ fontSize: 12, color: '#888' }}>
                    分支：{branches.find((b) => b.id === r.branch_id)?.name || '-'}
                  </span>
                  <span style={{ fontSize: 13 }}>{r.description || '无描述'}</span>
                  <Space wrap size={4}>
                    <Button size="small" onClick={() => openPersons(r)}>{r.person_count} 人参与</Button>
                    {writeable && (
                      <>
                        <Button size="small" onClick={() => {
                          setEditing(r); form.setFieldsValue(r); setOpen(true)
                        }}>编辑</Button>
                        <Popconfirm title="确认删除该事件？"
                          onConfirm={async () => {
                            await api.del(`/api/families/${familyId}/events/${r.id}`)
                            load()
                          }}>
                          <Button size="small" danger>删除</Button>
                        </Popconfirm>
                      </>
                    )}
                  </Space>
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

      <Modal open={open} title={editing ? '编辑事件' : '添加事件'} onCancel={() => setOpen(false)}
        onOk={save} destroyOnClose>
        <Form form={form} layout="vertical">
          <Form.Item name="name" label="事件名称" rules={[{ required: true }]}>
            <Input />
          </Form.Item>
          <Space size={12} wrap>
            <Form.Item name="time" label="时间" rules={[{ required: true }]}>
              <DateInput />
            </Form.Item>
            <Form.Item name="place" label="地点">
              <Input />
            </Form.Item>
            <Form.Item name="type" label="事件类型">
              <Select
                style={{ width: 130 }}
                options={Object.entries(EVENT_TYPES).map(([k, v]) => ({ value: Number(k), label: v }))}
              />
            </Form.Item>
            <Form.Item name="branch_id" label="关联分支">
              <Select
                allowClear
                style={{ width: 160 }}
                options={branches.map((b) => ({ value: b.id, label: b.name }))}
              />
            </Form.Item>
          </Space>
          <Form.Item name="description" label="描述">
            <Input.TextArea rows={3} />
          </Form.Item>
        </Form>
      </Modal>

      <Drawer
        open={!!personsFor}
        title={`参与人 - ${personsFor?.name}`}
        width={Math.min(560, window.innerWidth - 32)}
        onClose={() => setPersonsFor(null)}
      >
        {writeable && (
          <Form form={addForm} layout="vertical" onFinish={addParticipant}>
            <Space.Compact style={{ width: '100%' }}>
              <Form.Item name="person_id" style={{ flex: 1 }} rules={[{ required: true }]}>
                <PersonSelect />
              </Form.Item>
              <Form.Item name="role" style={{ width: 130 }} initialValue="参与者">
                <Select options={[{ value: '组织者', label: '组织者' }, { value: '参与者', label: '参与者' }]} />
              </Form.Item>
              <Form.Item>
                <Button type="primary" htmlType="submit">添加</Button>
              </Form.Item>
            </Space.Compact>
          </Form>
        )}
        <Table
          rowKey="id"
          size="small"
          dataSource={participants}
          pagination={false}
          columns={[
            { title: '成员', dataIndex: 'name' },
            { title: '世代', dataIndex: 'generation', width: 70 },
            { title: '角色', dataIndex: 'role', width: 100 },
            {
              title: '操作',
              width: 70,
              render: (_: any, r: any) =>
                writeable ? (
                  <Button
                    size="small"
                    danger
                    onClick={async () => {
                      await api.del(`/api/families/${familyId}/events/${personsFor!.id}/persons/${r.id}`)
                      setParticipants(
                        await api.get(`/api/families/${familyId}/events/${personsFor!.id}/persons`))
                    }}
                  >
                    移除
                  </Button>
                ) : null,
            },
          ]}
        />
      </Drawer>
    </Card>
  )
}
