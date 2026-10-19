import { appUrl } from '../../url'
import { useEffect, useState } from 'react'
import { Button, Card, Table } from 'antd'
import { useStore } from '../../store'
import { api } from '../../api'

export default function Logs() {
  const { user } = useStore()
  const [rows, setRows] = useState<any[]>([])
  useEffect(() => {
    api.get('/api/admin/logs?limit=200').then(setRows).catch(() => {})
  }, [])
  return (
    <Card
      title="操作日志"
      extra={<Button onClick={() => window.open(appUrl('/api/admin/logs/export?limit=10000'), '_blank')}>导出 CSV</Button>}
    >
      <Table
        rowKey="id"
        dataSource={rows}
        size="small"
        scroll={{ x: 800 }}
        pagination={{ pageSize: user?.page_size || 50 }}
        columns={[
          { title: '时间', dataIndex: 'created_at', width: 170 },
          { title: '用户', dataIndex: 'username', width: 120 },
          { title: '动作', dataIndex: 'action', width: 140 },
          { title: '对象', render: (_, r) => (r.target_type ? `${r.target_type}#${r.target_id ?? ''}` : '-'), width: 130 },
          { title: '详情', dataIndex: 'detail' },
          { title: 'IP', dataIndex: 'ip', width: 130 },
        ]}
      />
    </Card>
  )
}
