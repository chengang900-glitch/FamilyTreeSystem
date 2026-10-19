import { useState } from 'react'
import { Avatar, Button, Drawer, Dropdown, Layout, Menu, Select, Space, Typography, theme } from 'antd'
import {
  AppstoreOutlined, BranchesOutlined, BookOutlined, FileImageOutlined,
  HomeOutlined, LogoutOutlined, MenuOutlined, PrinterOutlined, ProfileOutlined,
  SettingOutlined, TeamOutlined, UserOutlined, ApartmentOutlined, SwapOutlined,
  DatabaseOutlined, CalendarOutlined, HeartOutlined, SafetyCertificateOutlined,
  MoonOutlined, SunOutlined,
} from '@ant-design/icons'
import { Outlet, useLocation, useNavigate } from 'react-router-dom'
import { message } from 'antd'
import { api } from '../api'
import { useStore } from '../store'

const { Header, Sider, Content } = Layout

export default function AppLayout() {
  const { user, familyId, setFamily, clear, dark, toggleDark } = useStore()
  const { token } = theme.useToken()
  const nav = useNavigate()
  const loc = useLocation()
  const [moreOpen, setMoreOpen] = useState(false)
  const mobile = window.innerWidth < 768
  const fam = user?.families.find((f) => f.id === familyId)
  const writeable = !!fam && (fam.role === 'admin' || !!user?.is_superuser)

  const familyMenu = fam
    ? [
        { key: '/persons', icon: <UserOutlined />, label: '成员管理' },
        { key: '/marriages', icon: <HeartOutlined />, label: '婚姻管理' },
        { key: '/parentchild', icon: <ApartmentOutlined />, label: '亲子管理' },
        { key: '/branches', icon: <BranchesOutlined />, label: '分支房系' },
        { key: '/events', icon: <CalendarOutlined />, label: '家族事件' },
        { key: '/resources', icon: <FileImageOutlined />, label: '文献资源' },
        { key: '/pedigree', icon: <AppstoreOutlined />, label: '世系树' },
        { key: '/exchange', icon: <SwapOutlined />, label: '导入导出' },
        { key: '/print', icon: <PrinterOutlined />, label: '族谱付印' },
        ...(writeable ? [
          { key: '/members', icon: <TeamOutlined />, label: '家谱成员' },
          { key: '/family-logs', icon: <SafetyCertificateOutlined />, label: '本谱日志' },
          { key: '/backup', icon: <DatabaseOutlined />, label: '备份与恢复' },
        ] : []),
      ]
    : []

  const adminMenu = user?.is_superuser
    ? [
        { key: '/admin/users', icon: <TeamOutlined />, label: '用户管理' },
        { key: '/admin/families', icon: <BookOutlined />, label: '家谱管理' },
        { key: '/admin/settings', icon: <SettingOutlined />, label: '系统设置' },
        { key: '/admin/logs', icon: <SafetyCertificateOutlined />, label: '操作日志' },
      ]
    : []

  const items = [
    { key: '/', icon: <HomeOutlined />, label: '首页' },
    ...familyMenu,
    ...(adminMenu.length
      ? [{ key: 'admin-group', type: 'group' as const, label: '系统管理', children: adminMenu }]
      : []),
    { key: '/profile', icon: <ProfileOutlined />, label: '个人中心' },
  ]

  const logout = async () => {
    await api.post('/api/auth/logout')
    clear()
    nav('/login')
  }

  const header = (
    <Header
      style={{
        background: token.colorBgContainer, display: 'flex', alignItems: 'center',
        justifyContent: 'space-between', padding: mobile ? '0 12px' : '0 24px',
        borderBottom: `1px solid ${token.colorBorderSecondary}`,
      }}
    >
      <Space size={8}>
        {mobile && (
          <Button type="text" icon={<MenuOutlined />} onClick={() => setMoreOpen(true)} />
        )}
        <Typography.Text strong style={{ fontSize: 16 }}>
          {fam ? fam.name : (user?.site_name || '家谱管理系统')}
        </Typography.Text>
      </Space>
      <Space size={8}>
        {!mobile && user && user.families.length > 0 && (
          <Select
            size="small"
            style={{ minWidth: 160 }}
            value={familyId || undefined}
            onChange={(v) => setFamily(v)}
            options={user.families.map((f) => ({
              value: f.id,
              label: `${f.name}${f.role === 'admin' ? '（管理员）' : ''}`,
            }))}
          />
        )}
        <Button
          type="text"
          aria-label="切换主题"
          icon={dark ? <SunOutlined /> : <MoonOutlined />}
          onClick={toggleDark}
        />
        <Dropdown
          menu={{
            items: [
              { key: 'profile', icon: <ProfileOutlined />, label: '个人中心' },
              { key: 'logout', icon: <LogoutOutlined />, label: '退出登录' },
            ],
            onClick: ({ key }) => (key === 'logout' ? logout() : nav('/profile')),
          }}
        >
          <Space style={{ cursor: 'pointer' }}>
            <Avatar size="small" icon={<UserOutlined />} />
            {!mobile && <span>{user?.real_name || user?.username}</span>}
          </Space>
        </Dropdown>
      </Space>
    </Header>
  )

  const bottomTabs = [
    { key: '/', icon: <HomeOutlined />, label: '首页' },
    { key: '/persons', icon: <UserOutlined />, label: '成员' },
    { key: '/pedigree', icon: <AppstoreOutlined />, label: '世系' },
    { key: '/profile', icon: <ProfileOutlined />, label: '我的' },
  ]

  return (
    <Layout style={{ minHeight: '100vh' }}>
      {!mobile && (
        <Sider theme={dark ? 'dark' : 'light'} width={200}
          style={{ borderRight: `1px solid ${token.colorBorderSecondary}` }}>
          <div style={{ padding: '16px 20px', fontWeight: 600, fontSize: 15 }}>
            <DatabaseOutlined /> 家谱管理
          </div>
          <Menu
            mode="inline"
            selectedKeys={[loc.pathname]}
            items={items as any}
            onClick={({ key }) => key.startsWith('/') && nav(key)}
          />
        </Sider>
      )}
      <Layout>
        {header}
        <Content style={{ padding: mobile ? 12 : 20, background: token.colorBgLayout,
          paddingBottom: mobile ? 76 : 20 }}>
          <Outlet />
        </Content>
      </Layout>

      {mobile && (
        <>
          <div
            style={{
              position: 'fixed', left: 0, right: 0, bottom: 0, background: '#fff',
              borderTop: '1px solid #eee', display: 'flex', zIndex: 20,
              paddingBottom: 'env(safe-area-inset-bottom)',
            }}
          >
            {bottomTabs.map((t) => (
              <div
                key={t.key}
                onClick={() => nav(t.key)}
                style={{
                  flex: 1, textAlign: 'center', padding: '8px 0', fontSize: 12,
                  color: loc.pathname === t.key ? '#8c6b4f' : '#888',
                }}
              >
                <div style={{ fontSize: 20 }}>{t.icon}</div>
                {t.label}
              </div>
            ))}
            <div
              onClick={() => setMoreOpen(true)}
              style={{ flex: 1, textAlign: 'center', padding: '8px 0', fontSize: 12, color: '#888' }}
            >
              <div style={{ fontSize: 20 }}><MenuOutlined /></div>
              更多
            </div>
          </div>
          <Drawer
            placement="left"
            open={moreOpen}
            onClose={() => setMoreOpen(false)}
            width={240}
            styles={{ body: { padding: 0 } }}
          >
            {user && user.families.length > 0 && (
              <div style={{ padding: 12, borderBottom: '1px solid #f0f0f0' }}>
                <Select
                  style={{ width: '100%' }}
                  value={familyId || undefined}
                  onChange={(v) => {
                    setFamily(v)
                    setMoreOpen(false)
                  }}
                  options={user.families.map((f) => ({
                    value: f.id,
                    label: `${f.name}${f.role === 'admin' ? '（管理员）' : ''}`,
                  }))}
                />
              </div>
            )}
            <Menu
              mode="inline"
              selectedKeys={[loc.pathname]}
              items={items as any}
              onClick={({ key }) => {
                setMoreOpen(false)
                if (key.startsWith('/')) nav(key)
              }}
            />
          </Drawer>
        </>
      )}
    </Layout>
  )
}
