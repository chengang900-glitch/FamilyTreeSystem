import { useEffect, useState } from 'react'
import {
  Button, Card, Drawer, Form, Input, Modal, Popconfirm, Select, Space, Switch, Table, Tag, message,
} from 'antd'
import { PlusOutlined } from '@ant-design/icons'
import { api } from '../../api'
import { useStore } from '../../store'

interface FamilyRow {
  id: number
  name: string
  slug: string
  surname: string
  hall_name: string
  visibility: number
  status: number
  member_count: number
  person_count: number
}

export default function Families() {
  const { user } = useStore()
  const [rows, setRows] = useState<FamilyRow[]>([])
  const [open, setOpen] = useState(false)
  const [editing, setEditing] = useState<FamilyRow | null>(null)
  const [form] = Form.useForm()
  const [memberFor, setMemberFor] = useState<FamilyRow | null>(null)
  const [members, setMembers] = useState<any[]>([])
  const [users, setUsers] = useState<any[]>([])
  const [addForm] = Form.useForm()

  const load = async () => {
    try {
      setRows(await api.get('/api/admin/families'))
    } catch (e: any) {
      message.error(e.message)
    }
  }

  useEffect(() => {
    load()
  }, [])

  const openMembers = async (row: FamilyRow) => {
    setMemberFor(row)
    setMembers(await api.get(`/api/admin/families/${row.id}/members`))
    setUsers(await api.get('/api/admin/users'))
    addForm.resetFields()
  }

  const save = async () => {
    const v = await form.validateFields()
    if (editing) {
      await api.put(`/api/admin/families/${editing.id}`, v)
    } else {
      await api.post('/api/admin/families', v)
    }
    message.success('已保存')
    setOpen(false)
    load()
  }

  const addMember = async () => {
    const v = await addForm.validateFields()
    await api.post(`/api/admin/families/${memberFor!.id}/members`, v)
    message.success('已加入')
    addForm.resetFields()
    setMembers(await api.get(`/api/admin/families/${memberFor!.id}/members`))
  }

  return (
    <Card
      title="家谱管理"
      extra={
        <Button
          type="primary"
          icon={<PlusOutlined />}
          onClick={() => {
            setEditing(null)
            form.resetFields()
            form.setFieldsValue({ visibility: 0, status: 1, generation_frozen: false })
            setOpen(true)
          }}
        >
          新建家谱
        </Button>
      }
    >
      <Table
        rowKey="id"
        dataSource={rows}
        pagination={{ pageSize: user?.page_size || 50 }}
        scroll={{ x: 900 }}
        columns={[
          { title: '名称', dataIndex: 'name', width: 160 },
          { title: '姓氏', dataIndex: 'surname', width: 80 },
          { title: '堂号', dataIndex: 'hall_name', width: 100 },
          { title: '标识', dataIndex: 'slug', width: 100 },
          { title: '成员数', dataIndex: 'member_count', width: 90 },
          { title: '族人数', dataIndex: 'person_count', width: 90 },
          {
            title: '状态',
            width: 80,
            render: (_, r) => (r.status ? <Tag color="green">正常</Tag> : <Tag>归档</Tag>),
          },
          {
            title: '操作',
            width: 220,
            fixed: 'right',
            render: (_, r) => (
              <Space size={4}>
                <Button size="small" onClick={() => openMembers(r)}>成员</Button>
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
                  title="删除将清空该家谱全部数据，确认继续？"
                  onConfirm={async () => {
                    await api.del(`/api/admin/families/${r.id}`)
                    message.success('已删除')
                    load()
                  }}
                >
                  <Button size="small" danger>删除</Button>
                </Popconfirm>
              </Space>
            ),
          },
        ]}
      />

      <Modal
        open={open}
        title={editing ? '编辑家谱' : '新建家谱'}
        onCancel={() => setOpen(false)}
        onOk={save}
        destroyOnClose
      >
        <Form form={form} layout="vertical">
          <Form.Item name="name" label="家谱名称" rules={[{ required: true }]}>
            <Input placeholder="如：张氏家谱" />
          </Form.Item>
          <Form.Item name="surname" label="姓氏">
            <Input />
          </Form.Item>
          <Form.Item name="hall_name" label="堂号">
            <Input />
          </Form.Item>
          <Form.Item name="origin_place" label="发源地">
            <Input />
          </Form.Item>
          <Form.Item name="compiler" label="修辑者">
            <Input />
          </Form.Item>
          <Form.Item name="generation_chars" label="字辈">
            <Input placeholder="如：木火土金水" />
          </Form.Item>
          <Form.Item name="generation_frozen" label="冻结字辈" valuePropName="checked">
            <Switch />
          </Form.Item>
          <Form.Item name="status" label="正常状态" valuePropName="checked">
            <Switch />
          </Form.Item>
          <Form.Item name="description" label="简介">
            <Input.TextArea rows={2} />
          </Form.Item>
        </Form>
      </Modal>

      <Drawer
        open={!!memberFor}
        title={`家谱成员 - ${memberFor?.name}`}
        width={Math.min(520, window.innerWidth - 32)}
        onClose={() => setMemberFor(null)}
      >
        <Form form={addForm} layout="vertical" onFinish={addMember}>
          <Space.Compact style={{ width: '100%' }}>
            <Form.Item name="user_id" style={{ flex: 1, marginBottom: 8 }} rules={[{ required: true }]}>
              <Select
                showSearch
                placeholder="选择用户"
                optionFilterProp="label"
                options={users.map((u) => ({
                  value: u.id,
                  label: `${u.username}${u.real_name ? '（' + u.real_name + '）' : ''}`,
                }))}
              />
            </Form.Item>
            <Form.Item name="role" style={{ width: 120, marginBottom: 8 }} initialValue="member">
              <Select
                options={[
                  { value: 'member', label: '普通用户' },
                  { value: 'admin', label: '家谱管理员' },
                ]}
              />
            </Form.Item>
            <Form.Item style={{ marginBottom: 8 }}>
              <Button type="primary" htmlType="submit">添加</Button>
            </Form.Item>
          </Space.Compact>
        </Form>
        <Table
          rowKey="id"
          size="small"
          dataSource={members}
          pagination={false}
          columns={[
            { title: '账号', dataIndex: 'username' },
            { title: '姓名', dataIndex: 'real_name' },
            {
              title: '角色',
              width: 130,
              render: (_, r) => (
                <Select
                  size="small"
                  value={r.role}
                  style={{ width: 110 }}
                  onChange={async (v) => {
                    try {
                      await api.put(`/api/admin/families/${memberFor!.id}/members/${r.id}`, { role: v })
                      message.success('已更新')
                      setMembers(await api.get(`/api/admin/families/${memberFor!.id}/members`))
                    } catch (e: any) {
                      message.error(e.message)
                    }
                  }}
                  options={[
                    { value: 'admin', label: '家谱管理员' },
                    { value: 'member', label: '普通用户' },
                  ]}
                />
              ),
            },
            {
              title: '操作',
              width: 70,
              render: (_, r) => (
                <Popconfirm
                  title="移出该家谱？"
                  onConfirm={async () => {
                    await api.del(`/api/admin/families/${memberFor!.id}/members/${r.id}`)
                    setMembers(await api.get(`/api/admin/families/${memberFor!.id}/members`))
                  }}
                >
                  <Button size="small" danger>移出</Button>
                </Popconfirm>
              ),
            },
          ]}
        />
      </Drawer>
    </Card>
  )
}
