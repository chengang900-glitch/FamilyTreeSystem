import { useEffect, useState } from 'react'
import { Button, Card, Checkbox, Form, Input, Typography, message } from 'antd'
import { BookOutlined, LockOutlined, UserOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { api } from '../api'
import { useStore } from '../store'

export default function Login() {
  const [form] = Form.useForm()
  const [loading, setLoading] = useState(false)
  const nav = useNavigate()
  const { load, user } = useStore()

  useEffect(() => {
    if (user) nav('/', { replace: true })
  }, [user, nav])

  const submit = async (values: any) => {
    setLoading(true)
    try {
      const data = await api.post('/api/auth/login', {
        username: values.username,
        password: values.password,
        remember: values.remember,
      })
      await load()
      if (data.must_change_pwd) {
        message.warning('首次登录，请先修改密码')
        nav('/profile')
      } else {
        nav('/')
      }
    } catch (e: any) {
      message.error(e.message || '登录失败')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div
      style={{
        minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center',
        background: '#f7f5f2', padding: 16,
      }}
    >
      <Card style={{ width: 380, maxWidth: '100%' }} styles={{ body: { padding: 28 } }}>
        <div style={{ textAlign: 'center', marginBottom: 20 }}>
          <BookOutlined style={{ fontSize: 34, color: '#8c6b4f' }} />
          <Typography.Title level={4} style={{ marginTop: 8, marginBottom: 0 }}>
            家谱管理系统
          </Typography.Title>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            把一族的来处，稳稳存下来
          </Typography.Text>
        </div>
        <Form form={form} layout="vertical" onFinish={submit} requiredMark={false}>
          <Form.Item name="username" label="账号" rules={[{ required: true, message: '请输入账号' }]}>
            <Input size="large" prefix={<UserOutlined />} autoComplete="username" />
          </Form.Item>
          <Form.Item name="password" label="密码" rules={[{ required: true, message: '请输入密码' }]}>
            <Input.Password size="large" prefix={<LockOutlined />} autoComplete="current-password" />
          </Form.Item>
          <Form.Item name="remember" valuePropName="checked" initialValue={false}>
            <Checkbox>记住登录（7 天）</Checkbox>
          </Form.Item>
          <Button type="primary" size="large" block loading={loading} htmlType="submit">
            登录
          </Button>
        </Form>
      </Card>
    </div>
  )
}
