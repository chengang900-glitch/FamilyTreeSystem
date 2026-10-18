import { useEffect, useState } from 'react'
import {
  Button, Card, Drawer, Form, Input, Modal, Popconfirm, Select, Space, Table, Tag, message,
} from 'antd'
import { PlusOutlined } from '@ant-design/icons'
import { api } from '../api'
import { useStore } from '../store'
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
  const [people, setPeople] = useState<any[]>([])
  const [open, setOpen] = useState(false)
  const [editing, setEditing] = useState<Row | null>(null)
  const [form] = Form.useForm()
  const [personsFor, setPersonsFor] = useState<Row | null>(null)
  const [participants, setParticipants] = useState<any[]>([])
  const [addForm] = Form.useForm()

  const load = async () => {
    if (!familyId) return
    try {
      setRows(await api.get(`/api/families/${familyId}/events`))
      setBranches(await api.get(`/api/families/${familyId}/branches`))
      const p = await api.get(`/api/families/${familyId}/persons?size=200`)
      setPeople(p.items)
    } catch (e: any) {
      message.error(e.message)
    }
  }

  useEffect(() => {
    load()
  }, [familyId])

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
      <Table
        rowKey="id"
        dataSource={rows}
        scroll={{ x: 900 }}
        columns={[
          { title: '事件名称', dataIndex: 'name', width: 160 },
          { title: '时间', dataIndex: 'time', width: 130 },
          { title: '地点', dataIndex: 'place', width: 140 },
          {
            title: '类型',
            dataIndex: 'type',
            width: 100,
            render: (t: number) => <Tag>{EVENT_TYPES[t]}</Tag>,
          },
          {
            title: '关联分支',
            width: 110,
            render: (_: any, r: Row) => branches.find((b) => b.id === r.branch_id)?.name || '-',
          },
          { title: '描述', dataIndex: 'description' },
          {
            title: '参与人',
            width: 90,
            render: (_: any, r: Row) => (
              <Button size="small" onClick={() => openPersons(r)}>{r.person_count} 人</Button>
            ),
          },
          {
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
        ]}
      />

      <Modal open={open} title={editing ? '编辑事件' : '添加事件'} onCancel={() => setOpen(false)}
        onOk={save} destroyOnClose>
        <Form form={form} layout="vertical">
          <Form.Item name="name" label="事件名称" rules={[{ required: true }]}>
            <Input />
          </Form.Item>
          <Space size={12} wrap>
            <Form.Item name="time" label="时间" rules={[{ required: true }]}>
              <Input placeholder="如：1990-03-12" />
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
                <Select
                  showSearch
                  optionFilterProp="label"
                  placeholder="选择成员"
                  options={people.map((p) => ({ value: p.id, label: `第${p.generation}世 ${p.name}` }))}
                />
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
