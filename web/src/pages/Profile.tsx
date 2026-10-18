import { Button, Card, Descriptions, Form, Input, Tag, message } from 'antd'
import { api } from '../api'
import { useStore } from '../store'

export default function Profile() {
  const { user, load } = useStore()
  const [form] = Form.useForm()

  const submit = async (v: any) => {
    try {
      await api.put('/api/auth/password', {
        old_password: v.old_password,
        new_password: v.new_password,
      })
      message.success('密码已更新')
      form.resetFields()
      load()
    } catch (e: any) {
      message.error(e.message)
    }
  }

  if (!user) return null

  return (
    <div>
      <Card title="账号信息" style={{ marginBottom: 16 }}>
        <Descriptions column={1} size="small">
          <Descriptions.Item label="账号">{user.username}</Descriptions.Item>
          <Descriptions.Item label="姓名">{user.real_name || '-'}</Descriptions.Item>
          <Descriptions.Item label="角色">
            {user.is_superuser ? <Tag color="red">超级管理员</Tag> : <Tag>普通用户</Tag>}
          </Descriptions.Item>
          <Descriptions.Item label="所属家谱">
            {user.families.map((f) => (
              <Tag key={f.id} color={f.role === 'admin' ? 'orange' : 'green'}>
                {f.name}
              </Tag>
            ))}
          </Descriptions.Item>
        </Descriptions>
      </Card>
      <Card title="修改密码">
        <Form form={form} layout="vertical" onFinish={submit} style={{ maxWidth: 380 }}>
          <Form.Item name="old_password" label="原密码" rules={[{ required: true }]}>
            <Input.Password autoComplete="current-password" />
          </Form.Item>
          <Form.Item
            name="new_password"
            label="新密码"
            rules={[{ required: true, min: 8, message: '至少 8 位，且含字母与数字' }]}
          >
            <Input.Password autoComplete="new-password" />
          </Form.Item>
          <Form.Item
            name="confirm"
            label="确认新密码"
            dependencies={['new_password']}
            rules={[
              { required: true },
              ({ getFieldValue }) => ({
                validator(_, value) {
                  return value === getFieldValue('new_password')
                    ? Promise.resolve()
                    : Promise.reject(new Error('两次输入不一致'))
                },
              }),
            ]}
          >
            <Input.Password autoComplete="new-password" />
          </Form.Item>
          <Button type="primary" htmlType="submit">保存</Button>
        </Form>
      </Card>
    </div>
  )
}
