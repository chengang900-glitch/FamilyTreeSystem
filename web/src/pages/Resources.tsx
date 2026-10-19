import { appUrl } from '../url'
import { useEffect, useState } from 'react'
import {
  Button, Card, Drawer, Form, Input, Modal, Pagination, Popconfirm, Progress, Segmented, Select, Space, Table, Tag, Upload, message,
} from 'antd'
import { UploadOutlined } from '@ant-design/icons'
import { api } from '../api'
import { useStore } from '../store'
import EntitySelect from '../components/EntitySelect'
import ColumnSettings, { useColumnSettings } from '../components/ColumnSettings'
import { RESOURCE_TYPES } from '../constants'

interface Row {
  id: number
  name: string
  fid: string
  type: number
  file_size: number
  mime_type: string
  description: string
  created_at: string
}

const ENTITY_LABEL: Record<string, string> = {
  person: '成员', marriage: '婚姻', parentchild: '亲子', event: '事件', branch: '分支',
}

export default function Resources() {
  const { user, familyId } = useStore()
  const fam = user?.families.find((f) => f.id === familyId)
  const writeable = !!fam && (fam.role === 'admin' || !!user?.is_superuser)
  const [rows, setRows] = useState<Row[]>([])
  const [kw, setKw] = useState('')
  const [page, setPage] = useState(1)
  const [total, setTotal] = useState(0)
  const size = user?.page_size || 50
  const [view, setView] = useState<'table' | 'card'>(
    () => (localStorage.getItem('fts_resource_view') === 'card' ? 'card' : 'table'))
  const cols = useColumnSettings<any>('fts_resource_cols')
  const columnMeta = [
    { key: 'name', title: '资源名称' },
    { key: 'preview', title: '预览' },
    { key: 'type', title: '分类' },
    { key: 'size', title: '大小' },
    { key: 'description', title: '描述' },
    { key: 'created_at', title: '入库时间' },
    { key: 'actions', title: '操作' },
  ]
  const [open, setOpen] = useState(false)
  const [form] = Form.useForm()
  const [file, setFile] = useState<any>(null)
  const [progress, setProgress] = useState<number | null>(null)
  const [uploading, setUploading] = useState(false)
  const [relFor, setRelFor] = useState<Row | null>(null)
  const [relations, setRelations] = useState<any[]>([])
  const [relForm] = Form.useForm()
  const entityType = Form.useWatch('entity_type', relForm)

  const load = async () => {
    if (!familyId) return
    try {
      const qs = `page=${page}&size=${size}${kw ? `&keyword=${encodeURIComponent(kw)}` : ''}`
      const d = await api.get(`/api/families/${familyId}/resources?${qs}`)
      setRows(d.items)
      setTotal(d.total)
    } catch (e: any) {
      message.error(e.message)
    }
  }

  useEffect(() => {
    load()
  }, [familyId, page, size, kw])

  const upload = async () => {
    const v = await form.validateFields()
    if (!file) {
      message.warning('请选择文件')
      return
    }
    const fd = new FormData()
    fd.append('file', file)
    fd.append('name', v.name)
    fd.append('type', String(v.type))
    fd.append('description', v.description || '')
    setUploading(true)
    setProgress(0)
    try {
      await new Promise<void>((resolve, reject) => {
        const xhr = new XMLHttpRequest()
        xhr.open('POST', appUrl(`/api/families/${familyId}/resources`))
        xhr.withCredentials = true
        xhr.setRequestHeader('X-Requested-With', 'fetch')
        xhr.upload.onprogress = (e) => {
          if (e.lengthComputable) setProgress(Math.round((e.loaded / e.total) * 100))
        }
        xhr.onload = () => {
          try {
            const j = JSON.parse(xhr.responseText)
            if (xhr.status >= 200 && xhr.status < 300 && j.code === 0) resolve()
            else reject(new Error(j.msg || '上传失败'))
          } catch {
            reject(new Error('服务响应异常'))
          }
        }
        xhr.onerror = () => reject(new Error('上传失败'))
        xhr.send(fd)
      })
      message.success('资源已入库')
      setOpen(false)
      setFile(null)
      form.resetFields()
      load()
    } catch (e: any) {
      message.error(e.message)
    } finally {
      setUploading(false)
      setProgress(null)
    }
  }

  const openRelations = async (row: Row) => {
    relForm.resetFields()
    setRelFor(row)
    setRelations(await api.get(`/api/families/${familyId}/resources/${row.id}/relations`))
  }

  const addRelation = async () => {
    const v = await relForm.validateFields()
    try {
      await api.post(`/api/families/${familyId}/resources/${relFor!.id}/relations`, v)
      setRelations(await api.get(`/api/families/${familyId}/resources/${relFor!.id}/relations`))
      relForm.resetFields()
    } catch (e: any) {
      message.error(e.message)
    }
  }

  return (
    <Card
      title="文献资源"
      extra={
        writeable && (
          <Button type="primary" icon={<UploadOutlined />} onClick={() => setOpen(true)}>
            添加资源
          </Button>
        )
      }
    >
      <Space wrap style={{ marginBottom: 12 }}>
        <Input.Search
          allowClear
          placeholder="按资源名称搜索"
          style={{ width: 260 }}
          onSearch={(v) => { setKw(v); setPage(1) }}
          onChange={(e) => { if (!e.target.value) { setKw(''); setPage(1) } }}
        />
        <ColumnSettings columns={columnMeta} hidden={cols.hidden} onToggle={cols.toggle} />
        <Segmented
          size="small"
          value={view}
          onChange={(v) => {
            const next = v as 'table' | 'card'
            setView(next)
            localStorage.setItem('fts_resource_view', next)
          }}
          options={[{ value: 'table', label: '列表' }, { value: 'card', label: '卡片' }]}
        />
      </Space>
      {view === 'table' ? (
      <Table
        rowKey="id"
        dataSource={rows}
        pagination={{ current: page, pageSize: size, total, onChange: setPage, showSizeChanger: false }}
        scroll={{ x: 900 }}
        columns={cols.visible([
          { key: 'name', title: '资源名称', dataIndex: 'name', width: 180 },
          {
            key: 'preview',
            title: '预览',
            width: 72,
            render: (_, r: Row) => {
              const image = r.mime_type?.startsWith('image/') || r.type === 4
              if (!image) return '-'
              const src = appUrl(`/api/families/${familyId}/files/${r.id}?inline=1`)
              return (
                <a href={src} target="_blank" rel="noreferrer">
                  <img src={src} alt={r.name} loading="lazy"
                    style={{ width: 42, height: 42, objectFit: 'cover', borderRadius: 4 }} />
                </a>
              )
            },
          },
          {
            key: 'type',
            title: '分类',
            dataIndex: 'type',
            width: 110,
            render: (t: number) => <Tag>{RESOURCE_TYPES[t]}</Tag>,
          },
          {
            key: 'size',
            title: '大小',
            dataIndex: 'file_size',
            width: 100,
            render: (s: number) => (s ? `${(s / 1024).toFixed(1)} KB` : '-'),
          },
          { key: 'description', title: '描述', dataIndex: 'description' },
          { key: 'created_at', title: '入库时间', dataIndex: 'created_at', width: 170 },
          {
            key: 'actions',
            title: '操作',
            width: 200,
            fixed: 'right',
            render: (_: any, r: Row) => (
              <Space size={4}>
                <Button size="small" onClick={() => openRelations(r)}>关联</Button>
                <Button
                  size="small"
                  onClick={() => window.open(appUrl(`/api/families/${familyId}/files/${r.id}`), '_blank')}
                >
                  下载
                </Button>
                {writeable && (
                  <Popconfirm
                    title="确认删除该资源？文件将一并删除"
                    onConfirm={async () => {
                      await api.del(`/api/families/${familyId}/resources/${r.id}`)
                      load()
                    }}
                  >
                    <Button size="small" danger>删除</Button>
                  </Popconfirm>
                )}
              </Space>
            ),
          },
        ])}
      />
      ) : (
        <>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill,minmax(260px,1fr))', gap: 12 }}>
            {rows.map((r) => {
              const image = r.mime_type?.startsWith('image/') || r.type === 4
              const src = appUrl(`/api/families/${familyId}/files/${r.id}?inline=1`)
              return (
                <Card
                  key={r.id}
                  size="small"
                  title={r.name}
                  extra={<Tag>{RESOURCE_TYPES[r.type]}</Tag>}
                  cover={image ? <img src={src} alt={r.name} loading="lazy"
                    style={{ height: 120, width: '100%', objectFit: 'cover' }} /> : undefined}
                >
                  <Space direction="vertical" size={4} style={{ width: '100%' }}>
                    <span style={{ fontSize: 12, color: '#888' }}>
                      {r.file_size ? `${(r.file_size / 1024).toFixed(1)} KB` : '-'} · {r.created_at}
                    </span>
                    <span style={{ fontSize: 13 }}>{r.description || '无描述'}</span>
                    <Space wrap size={4}>
                      <Button size="small"
                        onClick={() => window.open(appUrl(`/api/families/${familyId}/files/${r.id}`), '_blank')}>
                        下载
                      </Button>
                      <Button size="small" onClick={() => openRelations(r)}>关联</Button>
                      {writeable && (
                        <Popconfirm title="确认删除该资源？文件将一并删除"
                          onConfirm={async () => {
                            await api.del(`/api/families/${familyId}/resources/${r.id}`)
                            load()
                          }}>
                          <Button size="small" danger>删除</Button>
                        </Popconfirm>
                      )}
                    </Space>
                  </Space>
                </Card>
              )
            })}
          </div>
          {total > size && (
            <Pagination
              simple
              current={page}
              pageSize={size}
              total={total}
              onChange={setPage}
              style={{ textAlign: 'center', marginTop: 12 }}
            />
          )}
        </>
      )}

      <Modal open={open} title="添加资源" onCancel={() => setOpen(false)} onOk={upload}
        confirmLoading={uploading} destroyOnClose>
        <Form form={form} layout="vertical" initialValues={{ type: 1 }}>
          <Form.Item name="name" label="资源名称" rules={[{ required: true }]}>
            <Input placeholder="如：光绪年间老谱" />
          </Form.Item>
          <Form.Item name="type" label="业务分类">
            <Select options={Object.entries(RESOURCE_TYPES).map(([k, v]) => ({ value: Number(k), label: v }))} />
          </Form.Item>
          <Form.Item label="文件" required>
            <Upload
              capture="environment"
              beforeUpload={(f) => {
                const maxMb = user?.upload_max_mb || 200
                if (f.size > maxMb * 1024 * 1024) {
                  message.error(`文件超过 ${maxMb}MB 上限`)
                  return Upload.LIST_IGNORE
                }
                setFile(f)
                return false
              }}
              maxCount={1}
              onRemove={() => setFile(null)}
              accept="image/*,.pdf,.doc,.docx,.xls,.xlsx,.txt,.zip,.mp4,.mp3"
            >
              <Button icon={<UploadOutlined />}>选择文件 / 拍照</Button>
            </Upload>
          </Form.Item>
          <Form.Item name="description" label="描述">
            <Input.TextArea rows={2} />
          </Form.Item>
          {progress !== null && <Progress percent={progress} size="small" />}
        </Form>
      </Modal>

      <Drawer
        open={!!relFor}
        title={`关联实体 - ${relFor?.name}`}
        width={Math.min(560, window.innerWidth - 32)}
        onClose={() => setRelFor(null)}
      >
        {writeable && (
          <Form form={relForm} layout="vertical" onFinish={addRelation}>
            <Space.Compact style={{ width: '100%' }}>
              <Form.Item name="entity_type" style={{ width: 120 }} rules={[{ required: true }]}>
                <Select
                  placeholder="实体类型"
                  onChange={() => relForm.setFieldValue('entity_id', undefined)}
                  options={Object.entries(ENTITY_LABEL).map(([k, v]) => ({ value: k, label: v }))}
                />
              </Form.Item>
              <Form.Item name="entity_id" style={{ flex: 1 }} rules={[{ required: true }]}>
                <EntitySelect key={`${familyId}-${entityType}`} entityType={entityType} />
              </Form.Item>
              <Form.Item>
                <Button type="primary" htmlType="submit">关联</Button>
              </Form.Item>
            </Space.Compact>
          </Form>
        )}
        <Table
          rowKey="id"
          size="small"
          dataSource={relations}
          pagination={false}
          columns={[
            {
              title: '实体类型',
              width: 90,
              render: (_: any, r: any) => ENTITY_LABEL[r.entity_type],
            },
            { title: '对象', render: (_: any, r: any) => r.entity_name || `#${r.entity_id}` },
            {
              title: '操作',
              width: 70,
              render: (_: any, r: any) =>
                writeable ? (
                  <Button
                    size="small"
                    danger
                    onClick={async () => {
                      await api.del(
                        `/api/families/${familyId}/resources/${relFor!.id}/relations/${r.id}`)
                      setRelations(
                        await api.get(`/api/families/${familyId}/resources/${relFor!.id}/relations`))
                    }}
                  >
                    移除
                  </Button>
                ) : null,
            },
          ]}
        />
      </Drawer>
    </Card>
  )
}
