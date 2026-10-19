import { appUrl } from '../url'
import { useEffect, useState } from 'react'
import { Alert, Button, Card, Form, Input, Modal, Progress, Select, Space, Steps, Tag, Upload, message } from 'antd'
import { DownloadOutlined, UploadOutlined } from '@ant-design/icons'
import { api } from '../api'
import { useStore } from '../store'

const MODULES = [
  { key: 'family', label: '项目元数据' },
  { key: 'branches', label: '分支信息' },
  { key: 'persons', label: '成员信息' },
  { key: 'marriages', label: '婚姻关系' },
  { key: 'parentchild', label: '亲子关系' },
  { key: 'events', label: '家族事件' },
  { key: 'eventpersons', label: '事件参与人' },
  { key: 'resources', label: '文献资源' },
  { key: 'resource_relations', label: '资源关联' },
]

export default function DataExchange() {
  const { user, familyId } = useStore()
  const fam = user?.families.find((f) => f.id === familyId)
  const writeable = !!fam && (fam.role === 'admin' || !!user?.is_superuser)
  const [format, setFormat] = useState('json')
  const [modules, setModules] = useState<string[]>(MODULES.map((m) => m.key))
  const [includeRes, setIncludeRes] = useState(false)
  const [strategy, setStrategy] = useState(user?.default_strategy || 'append')
  const [file, setFile] = useState<any>(null)
  const [result, setResult] = useState<any>(null)
  const [progress, setProgress] = useState<number | null>(null)
  const [uploading, setUploading] = useState(false)
  const [includeMetadata, setIncludeMetadata] = useState(false)

  useEffect(() => {
    if (user?.default_strategy) setStrategy(user.default_strategy)
  }, [user?.default_strategy])

  const doExport = () => {
    const qs = `format=${format}&include_resources=${includeRes}&modules=${modules.join(',')}`
    window.open(appUrl(`/api/families/${familyId}/export?${qs}`), '_blank')
  }

  const doImport = async () => {
    if (!file) {
      message.warning('请选择要导入的数据包')
      return
    }
    const fd = new FormData()
    fd.append('file', file)
    fd.append('strategy', strategy)
    fd.append('include_metadata', String(includeMetadata))
    setUploading(true)
    setProgress(0)
    try {
      const data = await new Promise<any>((resolve, reject) => {
        const xhr = new XMLHttpRequest()
        xhr.open('POST', appUrl(`/api/families/${familyId}/import`))
        xhr.withCredentials = true
        xhr.setRequestHeader('X-Requested-With', 'fetch')
        xhr.upload.onprogress = (e) => {
          if (e.lengthComputable) setProgress(Math.round((e.loaded / e.total) * 100))
        }
        xhr.onload = () => {
          try {
            const j = JSON.parse(xhr.responseText)
            if (xhr.status >= 200 && xhr.status < 300 && j.code === 0) resolve(j.data)
            else reject(new Error(j.msg || '导入失败'))
          } catch {
            reject(new Error('服务响应异常'))
          }
        }
        xhr.onerror = () => reject(new Error('导入失败'))
        xhr.send(fd)
      })
      setResult(data)
      message.success('导入完成')
      setFile(null)
      if (includeMetadata) await useStore.getState().load()
    } catch (e: any) {
      message.error(e.message)
    } finally {
      setUploading(false)
      setProgress(null)
    }
  }

  return (
    <div>
      <Card title="导出数据" style={{ marginBottom: 16 }}>
        <Space direction="vertical" style={{ width: '100%' }} size={12}>
          <Space wrap>
            <span>导出格式</span>
            <Select
              value={format}
              onChange={setFormat}
              style={{ width: 200 }}
              options={[
                { value: 'json', label: 'JSON（完整备份）' },
                { value: 'csv', label: 'CSV 压缩包（Excel 可查看）' },
                { value: 'gedcom', label: 'GEDCOM（.ged，可互通）' },
                { value: 'zup', label: 'ZUP（家谱交换包）' },
              ]}
            />
            <label>
              <input
                type="checkbox"
                checked={includeRes}
                onChange={(e) => setIncludeRes(e.target.checked)}
              /> 打包资源库文件
            </label>
          </Space>
          {format === 'gedcom' && <Alert type="info" showIcon message="GEDCOM 交换人物、婚姻和亲子关系，其他软件可能忽略本系统扩展字段。完整迁移请使用 JSON 或 ZUP，并勾选资源原件。" />}
          <div>
            <div style={{ marginBottom: 6 }}>导出内容</div>
            <Space wrap>
              {MODULES.map((m) => (
                <Tag.CheckableTag
                  key={m.key}
                  checked={modules.includes(m.key)}
                  onChange={(c) =>
                    setModules(c ? [...modules, m.key] : modules.filter((x) => x !== m.key))}
                >
                  {m.label}
                </Tag.CheckableTag>
              ))}
            </Space>
          </div>
          <Button type="primary" icon={<DownloadOutlined />} onClick={doExport}>
            导出
          </Button>
        </Space>
      </Card>

      {writeable && (
        <Card title="导入数据">
          <Space direction="vertical" style={{ width: '100%' }} size={12}>
            <Space wrap>
              <span>导入策略</span>
              <Select
                value={strategy}
                onChange={setStrategy}
                style={{ width: 200 }}
                options={[
                  { value: 'append', label: '追加（保留现有数据）' },
                  { value: 'overwrite', label: '覆盖（清空后导入）' },
                ]}
              />
              <Upload
                beforeUpload={(f) => {
                  setFile(f)
                  return false
                }}
                maxCount={1}
                onRemove={() => setFile(null)}
                accept=".json,.ged,.zip,.zup"
              >
                <Button icon={<UploadOutlined />}>选择 JSON / GEDCOM / ZIP / ZUP</Button>
              </Upload>
              <Button type="primary" onClick={() => {
                if (strategy === 'overwrite') Modal.confirm({ title: '覆盖导入将清空本谱现有业务数据和资源，确认继续？',
                  content: '建议先在“备份与恢复”中下载备份。', onOk: doImport })
                else doImport()
              }} loading={uploading}>开始导入</Button>
            </Space>
            <label><input type="checkbox" checked={includeMetadata} onChange={e => setIncludeMetadata(e.target.checked)} />
              同时导入项目资料（替换谱名、堂号、字辈、修辑者等；仅 JSON/ZIP/ZUP）
            </label>
            {progress !== null && <Progress percent={progress} size="small" />}
            {result && (
              <Space wrap>
                <Tag color="green">成员 {result.person}</Tag>
                <Tag color="green">婚姻 {result.marriage}</Tag>
                <Tag color="green">亲子 {result.parentchild}</Tag>
                <Tag color="green">事件 {result.event}</Tag>
                <Tag color="green">资源 {result.resource}</Tag>
                <Tag color="green">分支 {result.branch}</Tag>
              </Space>
            )}
          </Space>
        </Card>
      )}
    </div>
  )
}
