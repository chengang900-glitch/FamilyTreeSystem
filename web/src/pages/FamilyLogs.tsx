import { appUrl } from '../url'
import { useEffect, useState } from 'react'
import { Button, Card, Space, Table, Tag, message } from 'antd'
import { DownloadOutlined } from '@ant-design/icons'
import { api } from '../api'
import { useStore } from '../store'

function renderDetail(value: any) {
  if (!value) return '-'
  try {
    const obj = JSON.parse(value)
    if (obj && typeof obj === 'object' && !Array.isArray(obj)) {
      const parts = Object.entries(obj).map(([k, v]: [string, any]) => {
        if (v && typeof v === 'object' && 'old' in v) {
          return `${k}: ${format(v.old)} → ${format(v.new)}`
        }
        return `${k}: ${format(v)}`
      })
      return parts.length ? parts.join('；') : '-'
    }
  } catch {
    // 非 JSON 的历史 detail 按原样展示
  }
  return String(value)
}

function format(v: any) {
  if (v === null || v === undefined || v === '') return '空'
  return String(v)
}

const ACTION_LABEL: Record<string, string> = {
  create_person: '新增成员', update_person: '修改成员', delete_person: '删除成员',
  create_marriage: '新增婚姻', update_marriage: '修改婚姻', delete_marriage: '删除婚姻',
  create_parentchild: '新增亲子', update_parentchild: '修改亲子', delete_parentchild: '删除亲子',
  create_event: '新增事件', update_event: '修改事件', delete_event: '删除事件',
  upload_resource: '上传资源', update_resource: '修改资源', delete_resource: '删除资源',
  create_branch: '新增分支', update_branch: '修改分支', delete_branch: '删除分支',
  assign_branch_members: '批量归入分支', export: '导出', import: '导入',
  backup_family: '家谱备份', restore_family: '家谱恢复',
  grant_role: '授权', revoke_member: '移出成员', change_role: '变更角色',
}

export default function FamilyLogs() {
  const { user, familyId } = useStore()
  const [rows, setRows] = useState<any[]>([])
  const [loading, setLoading] = useState(false)

  const load = async () => {
    if (!familyId) return
    setLoading(true)
    try {
      setRows(await api.get(`/api/families/${familyId}/logs?limit=500`))
    } catch (e: any) {
      message.error(e.message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
  }, [familyId])

  return (
    <Card
      title="本谱操作日志"
      extra={
        <Space>
          <Button onClick={load} loading={loading}>刷新</Button>
          <Button
            icon={<DownloadOutlined />}
            onClick={() => window.open(appUrl(`/api/families/${familyId}/logs/export?limit=10000`), '_blank')}
          >
            导出 CSV
          </Button>
        </Space>
      }
    >
      <Table
        rowKey="id"
        dataSource={rows}
        size="small"
        scroll={{ x: 900 }}
        pagination={{ pageSize: user?.page_size || 50 }}
        columns={[
          { title: '时间', dataIndex: 'created_at', width: 170 },
          { title: '用户', dataIndex: 'username', width: 120 },
          {
            title: '动作',
            dataIndex: 'action',
            width: 140,
            render: (v: string) => <Tag>{ACTION_LABEL[v] || v}</Tag>,
          },
          { title: '对象', width: 130, render: (_, r) => (r.target_type ? `${r.target_type}#${r.target_id ?? ''}` : '-') },
          {
            title: '变更摘要',
            render: (_, r) => <span style={{ fontSize: 12 }}>{renderDetail(r.detail)}</span>,
          },
          { title: 'IP', dataIndex: 'ip', width: 130 },
        ]}
      />
    </Card>
  )
}
