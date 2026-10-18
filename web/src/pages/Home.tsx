import { Card, Empty, Row, Col, Typography, Button, Space, Tag, Statistic, Descriptions } from 'antd'
import { BookOutlined, PlusOutlined, UserOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { useStore } from '../store'

export default function Home() {
  const { user, familyId, setFamily } = useStore()
  const nav = useNavigate()
  const fam = user?.families.find((f) => f.id === familyId)

  if (!user) return null

  if (!fam) {
    return (
      <div>
        <Typography.Title level={4}>选择家谱</Typography.Title>
        {user.families.length === 0 ? (
          <Empty description="你还没有加入任何家谱，请联系管理员">
            {user.is_superuser && (
              <Button type="primary" onClick={() => nav('/admin/families')}>前往创建家谱</Button>
            )}
          </Empty>
        ) : (
          <Row gutter={[16, 16]}>
            {user.families.map((f) => (
              <Col key={f.id} xs={24} sm={12} md={8} lg={6}>
                <Card
                  hoverable
                  onClick={() => setFamily(f.id)}
                  styles={{ body: { padding: 16 } }}
                >
                  <Space direction="vertical" size={4} style={{ width: '100%' }}>
                    <Space>
                      <BookOutlined style={{ color: '#8c6b4f' }} />
                      <Typography.Text strong>{f.name}</Typography.Text>
                    </Space>
                    <Tag color={f.role === 'admin' ? 'orange' : 'green'}>
                      {f.role === 'admin' ? '家谱管理员' : '家族成员'}
                    </Tag>
                  </Space>
                </Card>
              </Col>
            ))}
          </Row>
        )}
      </div>
    )
  }

  const cards = [
    { key: '/persons', title: '成员管理', desc: '世代、姓名字号、生卒葬' },
    { key: '/marriages', title: '婚姻管理', desc: '配偶、次序、结缡与离婚' },
    { key: '/parentchild', title: '亲子管理', desc: '父母子女与生养关系' },
    { key: '/branches', title: '分支房系', desc: '堂号、字辈、家族训' },
    { key: '/events', title: '家族事件', desc: '时间、地点、参与人' },
    { key: '/resources', title: '文献资源', desc: '老谱、契约、影像' },
    { key: '/pedigree', title: '世系树', desc: '五种布局，一键成图' },
    { key: '/exchange', title: '导入导出', desc: 'JSON / CSV / GEDCOM' },
    { key: '/print', title: '族谱付印', desc: 'PDF / Word 成册' },
  ]

  return (
    <div>
      <Card styles={{ body: { padding: 20 } }} style={{ marginBottom: 16 }}>
        <Space align="start" style={{ width: '100%', justifyContent: 'space-between' }}>
          <div>
            <Typography.Title level={4} style={{ marginBottom: 4 }}>{fam.name}</Typography.Title>
            <Space size={8} wrap>
              <Tag color={fam.role === 'admin' ? 'orange' : 'green'}>
                {fam.role === 'admin' ? '家谱管理员' : '家族成员'}
              </Tag>
              {fam.visibility === 2 && <Tag color="blue">公开只读</Tag>}
            </Space>
          </div>
          <Button icon={<PlusOutlined />} onClick={() => nav('/persons')}>录入成员</Button>
        </Space>
      </Card>

      <Row gutter={[16, 16]}>
        {cards.map((c) => (
          <Col key={c.key} xs={12} sm={8} md={6} lg={4}>
            <Card hoverable onClick={() => nav(c.key)} styles={{ body: { padding: 14 } }}>
              <Typography.Text strong>{c.title}</Typography.Text>
              <div style={{ fontSize: 12, color: '#888', marginTop: 4 }}>{c.desc}</div>
            </Card>
          </Col>
        ))}
      </Row>
    </div>
  )
}
