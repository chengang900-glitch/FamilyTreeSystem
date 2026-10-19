import { appUrl } from '../url'
import { useEffect, useState } from 'react'
import { Alert, Button, Card, Popconfirm, Space, Table, Tag, Upload, message } from 'antd'
import { CloudDownloadOutlined, DatabaseOutlined, UploadOutlined } from '@ant-design/icons'
import { api } from '../api'
import { useStore } from '../store'

export default function Backup() {
  const { user, familyId } = useStore()
  const [file, setFile] = useState<any>(null)
  const [busy, setBusy] = useState(false)
  const [backups, setBackups] = useState<any[]>([])

  const isSuper = !!user?.is_superuser

  const loadBackups = async () => {
    if (!isSuper) return
    try {
      setBackups(await api.get('/api/admin/backups'))
    } catch (e: any) {
      message.error(e.message)
    }
  }

  useEffect(() => {
    loadBackups()
  }, [isSuper])

  const createGlobalBackup = async () => {
    setBusy(true)
    try {
      const d = await api.post('/api/admin/backup')
      message.success(`备份已生成：${d.file}`)
      await loadBackups()
    } catch (e: any) {
      message.error(e.message)
    } finally {
      setBusy(false)
    }
  }

  const restoreFamily = async () => {
    if (!file) {
      message.warning('请选择家谱备份 ZIP')
      return
    }
    setBusy(true)
    try {
      const fd = new FormData()
      fd.append('file', file)
      const res = await fetch(appUrl(`/api/families/${familyId}/restore`), {
        method: 'POST', body: fd, credentials: 'same-origin',
        headers: { 'X-Requested-With': 'fetch' },
      })
      const j = await res.json()
      if (j.code !== 0) throw new Error(j.msg)
      message.success('家谱数据已恢复')
      setFile(null)
    } catch (e: any) {
      message.error(e.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div>
      {familyId && (
        <Card title="本谱备份与恢复" style={{ marginBottom: 16 }}>
          <Alert
            type="warning"
            showIcon
            style={{ marginBottom: 12 }}
            message="恢复会用备份包覆盖本谱全部业务数据与资源，操作前建议先下载一份当前备份。"
          />
          <Space wrap>
            <Button
              type="primary"
              icon={<CloudDownloadOutlined />}
              onClick={() => window.open(appUrl(`/api/families/${familyId}/backup`), '_blank')}
            >
              下载本谱备份
            </Button>
            <Upload
              beforeUpload={(f) => { setFile(f); return false }}
              maxCount={1}
              accept=".zip"
              onRemove={() => setFile(null)}
            >
              <Button icon={<UploadOutlined />}>选择备份 ZIP</Button>
            </Upload>
            <Popconfirm
              title="确认用该备份覆盖本谱全部数据？"
              description="此操作不可撤销，建议先下载当前备份。"
              onConfirm={restoreFamily}
              okText="覆盖恢复"
              cancelText="取消"
            >
              <Button danger disabled={!file} loading={busy}>恢复本谱</Button>
            </Popconfirm>
          </Space>
          {file && <div style={{ marginTop: 8, color: '#888', fontSize: 12 }}>已选择：{file.name}</div>}
        </Card>
      )}

      {isSuper && (
        <Card
          title="全库备份"
          extra={<Button type="primary" icon={<DatabaseOutlined />} onClick={createGlobalBackup} loading={busy}>立即备份</Button>}
        >
          <Table
            rowKey="name"
            dataSource={backups}
            size="small"
            pagination={{ pageSize: user?.page_size || 50 }}
            columns={[
              { title: '文件名', dataIndex: 'name' },
              { title: '大小', dataIndex: 'size', width: 120, render: (n: number) => `${(n / 1024 / 1024).toFixed(2)} MB` },
              { title: '生成时间', dataIndex: 'time', width: 180 },
              {
                title: '操作', width: 100,
                render: (_, r) => (
                  <Button size="small" onClick={() => window.open(appUrl(`/api/admin/backups/${r.name}`), '_blank')}>
                    下载
                  </Button>
                ),
              },
            ]}
          />
          <Alert
            style={{ marginTop: 12 }}
            type="info"
            showIcon
            message="全库恢复请使用仓库 scripts/restore_backup.py，在停服状态下执行，避免运行中替换 SQLite 文件。"
          />
          <div style={{ marginTop: 8 }}>
            <Tag color="blue">备份包含 app.db + uploads</Tag>
          </div>
        </Card>
      )}
    </div>
  )
}
