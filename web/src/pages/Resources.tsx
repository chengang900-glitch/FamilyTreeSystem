import { useEffect, useState } from 'react'
import {
  Button, Card, Drawer, Form, Input, Modal, Popconfirm, Select, Space, Table, Tag, Upload, message,
} from 'antd'
import { UploadOutlined } from '@ant-design/icons'
import { api } from '../api'
import { useStore } from '../store'
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
  const [open, setOpen] = useState(false)
  const [form] = Form.useForm()
  const [file, setFile] = useState<any>(null)
  const [relFor, setRelFor] = useState<Row | null>(null)
  const [relations, setRelations] = useState<any[]>([])
  const [relForm] = Form.useForm()
  const [targets, setTargets] = useState<any[]>([])

  const load = async () => {
    if (!familyId) return
    try {
      setRows(await api.get(`/api/families/${familyId}/resources`))
    } catch (e: any) {
      message.error(e.message)
    }
  }

  useEffect(() => {
    load()
  }, [familyId])

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
    try {
      await fetch(`/api/families/${familyId}/resources`, {
        method: 'POST',
        body: fd,
        credentials: 'same-origin',
        headers: { 'X-Requested-With': 'fetch' },
      }).then(async (r) => {
        const j = await r.json()
        if (j.code !== 0) throw new Error(j.msg)
      })
      message.success('资源已入库')
      setOpen(false)
      setFile(null)
      form.resetFields()
      load()
    } catch (e: any) {
      message.error(e.message)
    }
  }

  const openRelations = async (row: Row) => {
    setRelFor(row)
    setRelations(await api.get(`/api/families/${familyId}/resources/${row.id}/relations`))
  }

  const loadTargets = async (type: string) => {
    if (!type) return setTargets([])
    const map: Record<string, string> = {
      person: 'persons', event: 'events', branch: 'branches', marriage: 'marriages',
      parentchild: 'parentchild',
    }
    const data = await api.get(`/api/families/${familyId}/${map[type]}?size=200`)
    setTargets((data.items || data).map((r: any) => ({
      value: r.id,
      label: r.name || `${r.spouse1_name} & ${r.spouse2_name}` || `#${r.id}`,
    })))
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
      <Table
        rowKey="id"
        dataSource={rows}
        scroll={{ x: 900 }}
        columns={[
          { title: '资源名称', dataIndex: 'name', width: 180 },
          {
            title: '分类',
            dataIndex: 'type',
            width: 110,
            render: (t: number) => <Tag>{RESOURCE_TYPES[t]}</Tag>,
          },
          {
            title: '大小',
            dataIndex: 'file_size',
            width: 100,
            render: (s: number) => (s ? `${(s / 1024).toFixed(1)} KB` : '-'),
          },
          { title: '描述', dataIndex: 'description' },
          { title: '入库时间', dataIndex: 'created_at', width: 170 },
          {
            title: '操作',
            width: 200,
            fixed: 'right',
            render: (_: any, r: Row) => (
              <Space size={4}>
                <Button size="small" onClick={() => openRelations(r)}>关联</Button>
                <Button
                  size="small"
                  onClick={() => window.open(`/api/families/${familyId}/files/${r.id}`, '_blank')}
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
        ]}
      />

      <Modal open={open} title="添加资源" onCancel={() => setOpen(false)} onOk={upload} destroyOnClose>
        <Form form={form} layout="vertical" initialValues={{ type: 1 }}>
          <Form.Item name="name" label="资源名称" rules={[{ required: true }]}>
            <Input placeholder="如：光绪年间老谱" />
          </Form.Item>
          <Form.Item name="type" label="业务分类">
            <Select options={Object.entries(RESOURCE_TYPES).map(([k, v]) => ({ value: Number(k), label: v }))} />
          </Form.Item>
          <Form.Item label="文件" required>
            <Upload
              beforeUpload={(f) => {
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
                  onChange={(v) => loadTargets(v)}
                  options={Object.entries(ENTITY_LABEL).map(([k, v]) => ({ value: k, label: v }))}
                />
              </Form.Item>
              <Form.Item name="entity_id" style={{ flex: 1 }} rules={[{ required: true }]}>
                <Select showSearch optionFilterProp="label" placeholder="选择对象" options={targets} />
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
