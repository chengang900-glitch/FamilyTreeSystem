import { useEffect, useState } from 'react'
import {
  Button, Card, Form, Input, Modal, Popconfirm, Select, Space, Switch, Table, Tag, message,
} from 'antd'
import { PlusOutlined } from '@ant-design/icons'
import { api } from '../../api'
import { useStore } from '../../store'

interface UserRow {
  id: number
  username: string
  real_name: string
  phone: string
  email: string
  status: number
  is_superuser: boolean
  must_change_pwd: boolean
  last_login_at: string
  families: { id: number; name: string; role: string }[]
}

export default function Users() {
  const { user: me } = useStore()
  const minPwd = me?.password_min_length || 8
  const strong = me?.password_require_strong !== false
  const pwdRules = [
    { required: true, min: minPwd, message: `至少 ${minPwd} 位${strong ? '，且含字母与数字' : ''}` },
    ...(strong ? [{ pattern: /^(?=.*[A-Za-z])(?=.*\d).+$/, message: '需同时包含字母与数字' }] : []),
  ]
  const [rows, setRows] = useState<UserRow[]>([])
  const [open, setOpen] = useState(false)
  const [editing, setEditing] = useState<UserRow | null>(null)
  const [form] = Form.useForm()
  const [kw, setKw] = useState('')
  const [resetFor, setResetFor] = useState<UserRow | null>(null)
  const [resetForm] = Form.useForm()

  const load = async () => {
    try {
      setRows(await api.get(`/api/admin/users?keyword=${encodeURIComponent(kw)}`))
    } catch (e: any) {
      message.error(e.message)
    }
  }

  useEffect(() => {
    load()
  }, [kw])

  const save = async () => {
    const v = await form.validateFields()
    if (editing) {
      await api.put(`/api/admin/users/${editing.id}`, v)
    } else {
      await api.post('/api/admin/users', v)
    }
    message.success('已保存')
    setOpen(false)
    load()
  }

  const resetPwd = async () => {
    const v = await resetForm.validateFields()
    await api.post(`/api/admin/users/${resetFor!.id}/reset-password`, { password: v.password })
    message.success('已重置，该用户下次登录需修改密码')
    setResetFor(null)
    resetForm.resetFields()
  }

  return (
    <Card
      title="用户管理"
      extra={
        <Space>
          <Input.Search
            placeholder="搜索账号/姓名/手机"
            allowClear
            onSearch={setKw}
            style={{ width: 200 }}
          />
          <Button
            type="primary"
            icon={<PlusOutlined />}
            onClick={() => {
              setEditing(null)
              form.resetFields()
              form.setFieldsValue({ status: 1, is_superuser: false, must_change_pwd: true })
              setOpen(true)
            }}
          >
            新建用户
          </Button>
        </Space>
      }
    >
      <Table
        rowKey="id"
        dataSource={rows}
        scroll={{ x: 900 }}
        pagination={{ pageSize: me?.page_size || 50 }}
        columns={[
          { title: '账号', dataIndex: 'username', width: 120 },
          { title: '姓名', dataIndex: 'real_name', width: 110 },
          { title: '手机', dataIndex: 'phone', width: 130 },
          {
            title: '系统角色',
            width: 110,
            render: (_, r) =>
              r.is_superuser ? <Tag color="red">超级管理员</Tag> : <Tag>普通用户</Tag>,
          },
          {
            title: '家谱角色',
            render: (_, r) =>
              r.families.map((f) => (
                <Tag key={f.id} color={f.role === 'admin' ? 'orange' : 'green'}>
                  {f.name}
                </Tag>
              )),
          },
          {
            title: '状态',
            width: 90,
            render: (_, r) => (r.status ? <Tag color="green">启用</Tag> : <Tag>停用</Tag>),
          },
          { title: '最后登录', dataIndex: 'last_login_at', width: 170 },
          {
            title: '操作',
            width: 200,
            fixed: 'right',
            render: (_, r) => (
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
                <Button size="small" onClick={() => setResetFor(r)}>重置密码</Button>
                <Popconfirm
                  title="确认删除该用户？"
                  onConfirm={async () => {
                    await api.del(`/api/admin/users/${r.id}`)
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
        title={editing ? '编辑用户' : '新建用户'}
        onCancel={() => setOpen(false)}
        onOk={save}
        destroyOnClose
      >
        <Form form={form} layout="vertical">
          <Form.Item
            name="username"
            label="账号"
            rules={[{ required: true, message: '请输入账号' }]}
          >
            <Input disabled={!!editing} placeholder="字母、数字、下划线，3-32 位" />
          </Form.Item>
          {!editing && (
            <Form.Item
              name="password"
              label="初始密码"
              rules={pwdRules}
            >
              <Input.Password />
            </Form.Item>
          )}
          {!editing && (
            <Form.Item
              name="must_change_pwd"
              label="首次登录需修改密码"
              valuePropName="checked"
              initialValue
            >
              <Switch />
            </Form.Item>
          )}
          <Form.Item name="real_name" label="姓名">
            <Input />
          </Form.Item>
          <Form.Item name="phone" label="手机">
            <Input />
          </Form.Item>
          <Form.Item name="email" label="邮箱">
            <Input />
          </Form.Item>
          <Form.Item name="is_superuser" label="超级管理员" valuePropName="checked">
            <Switch />
          </Form.Item>
          <Form.Item name="status" label="启用" valuePropName="checked">
            <Switch />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        open={!!resetFor}
        title={`重置密码 - ${resetFor?.username}`}
        onCancel={() => setResetFor(null)}
        onOk={resetPwd}
        destroyOnClose
      >
        <Form form={resetForm} layout="vertical">
          <Form.Item
            name="password"
            label="新密码"
            rules={pwdRules}
          >
            <Input.Password />
          </Form.Item>
        </Form>
      </Modal>
    </Card>
  )
}
