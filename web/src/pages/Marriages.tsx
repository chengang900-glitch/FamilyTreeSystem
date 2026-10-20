import { useEffect, useState } from 'react'
import {
  Alert, Button, Card, Form, Input, InputNumber, Modal, Pagination, Popconfirm, Segmented, Space, Table, Tag, message,
} from 'antd'
import { PlusOutlined } from '@ant-design/icons'
import { api } from '../api'
import { isMobile, useStore } from '../store'
import PersonSelect from '../components/PersonSelect'
import DateInput from '../components/DateInput'
import ColumnSettings, { useColumnSettings } from '../components/ColumnSettings'

interface Row {
  id: number
  spouse1_id: number
  spouse2_id: number
  spouse1_name: string
  spouse2_name: string
  marriage_order: number
  marriage_date: string
  divorce_date: string
  marriage_place: string
  description: string
  notes: string
}

export default function Marriages() {
  const { user, familyId } = useStore()
  const fam = user?.families.find((f) => f.id === familyId)
  const writeable = !!fam && (fam.role === 'admin' || !!user?.is_superuser)
  const [rows, setRows] = useState<Row[]>([])
  const [kw, setKw] = useState('')
  const [page, setPage] = useState(1)
  const [total, setTotal] = useState(0)
  const size = user?.page_size || 50
  const mobile = isMobile()
  const viewKey = mobile ? 'fts_marriage_view_mobile' : 'fts_marriage_view'
  const [view, setView] = useState<'table' | 'card'>(() => {
    const saved = localStorage.getItem(viewKey)
    return saved === 'table' || saved === 'card' ? saved : mobile ? 'card' : 'table'
  })
  const cols = useColumnSettings<any>('fts_marriage_cols')
  const columnMeta = [
    { key: 'spouse1_name', title: '成员 A' },
    { key: 'spouse2_name', title: '成员 B' },
    { key: 'marriage_order', title: '本段次序' },
    { key: 'marriage_date', title: '结婚日期' },
    { key: 'divorce_date', title: '离婚日期' },
    { key: 'marriage_place', title: '地点' },
    { key: 'description', title: '说明' },
    { key: 'actions', title: '操作' },
  ]
  const [open, setOpen] = useState(false)
  const [editing, setEditing] = useState<Row | null>(null)
  const [form] = Form.useForm()
  const spouse1 = Form.useWatch('spouse1_id', form)
  const spouse2 = Form.useWatch('spouse2_id', form)

  const load = async () => {
    if (!familyId) return
    try {
      const qs = `page=${page}&size=${size}${kw ? `&keyword=${encodeURIComponent(kw)}` : ''}`
      const d = await api.get(`/api/families/${familyId}/marriages?${qs}`)
      setRows(d.items)
      setTotal(d.total)
    } catch (e: any) {
      message.error(e.message)
    }
  }

  useEffect(() => {
    load()
  }, [familyId, page, size, kw])

  const save = async () => {
    const v = await form.validateFields()
    try {
      if (editing) await api.put(`/api/families/${familyId}/marriages/${editing.id}`, v)
      else await api.post(`/api/families/${familyId}/marriages`, v)
      message.success('已保存')
      setOpen(false)
      load()
    } catch (e: any) {
      message.error(e.message)
    }
  }

  return (
    <Card
      title="婚姻管理（每行一段婚姻）"
      extra={
        writeable && (
          <Button
            type="primary"
            icon={<PlusOutlined />}
            onClick={() => {
              setEditing(null)
              form.resetFields()
              form.setFieldsValue({ marriage_order: 1 })
              setOpen(true)
            }}
          >
            添加一段婚姻
          </Button>
        )
      }
    >
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 12 }}
        message="每条记录只维护一对婚姻关系；同一成员可以有多条记录，因此三段及以上婚姻也能完整登记。"
      />
      <Space wrap style={{ marginBottom: 12 }}>
        <Input.Search
          allowClear
          placeholder="按成员姓名筛选婚姻记录"
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
            localStorage.setItem(viewKey, next)
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
          { key: 'spouse1_name', title: '成员 A', dataIndex: 'spouse1_name', width: 120 },
          { key: 'spouse2_name', title: '成员 B', dataIndex: 'spouse2_name', width: 120 },
          { key: 'marriage_order', title: '本段次序', dataIndex: 'marriage_order', width: 90 },
          { key: 'marriage_date', title: '结婚日期', dataIndex: 'marriage_date', width: 130 },
          { key: 'divorce_date', title: '离婚日期', dataIndex: 'divorce_date', width: 130 },
          { key: 'marriage_place', title: '地点', dataIndex: 'marriage_place', width: 140 },
          { key: 'description', title: '说明', dataIndex: 'description' },
          {
            key: 'actions',
            title: '操作',
            width: 130,
            fixed: 'right',
            render: (_: any, r: Row) =>
              writeable ? (
                <Space size={4}>
                  <Button
                    size="small"
                    onClick={() => {
                      setEditing(r)
                      form.setFieldsValue(r)
                      setOpen(true)
                    }}
                  >
                    编辑
                  </Button>
                  <Popconfirm
                    title="确认删除该婚姻记录？"
                    onConfirm={async () => {
                      await api.del(`/api/families/${familyId}/marriages/${r.id}`)
                      message.success('已删除')
                      load()
                    }}
                  >
                    <Button size="small" danger>删除</Button>
                  </Popconfirm>
                </Space>
              ) : null,
          },
        ])}
      />
      ) : (
        <>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill,minmax(280px,1fr))', gap: 12 }}>
            {rows.map((m) => (
              <Card key={m.id} size="small" title={`${m.spouse1_name} & ${m.spouse2_name}`}
                extra={<Tag>第 {m.marriage_order} 段</Tag>}>
                <Space direction="vertical" size={4} style={{ width: '100%' }}>
                  <span style={{ fontSize: 12, color: '#888' }}>
                    结婚：{m.marriage_date || '不详'}　离婚：{m.divorce_date || '—'}
                  </span>
                  <span style={{ fontSize: 12, color: '#888' }}>地点：{m.marriage_place || '不详'}</span>
                  <span style={{ fontSize: 13 }}>{m.description || '无说明'}</span>
                  {writeable && (
                    <Space wrap size={4}>
                      <Button size="small" onClick={() => {
                        setEditing(m); form.setFieldsValue(m); setOpen(true)
                      }}>编辑</Button>
                      <Popconfirm title="确认删除该婚姻记录？"
                        onConfirm={async () => {
                          await api.del(`/api/families/${familyId}/marriages/${m.id}`)
                          message.success('已删除')
                          load()
                        }}>
                        <Button size="small" danger>删除</Button>
                      </Popconfirm>
                    </Space>
                  )}
                </Space>
              </Card>
            ))}
          </div>
          {total > size && (
            <Pagination simple current={page} pageSize={size} total={total}
              onChange={setPage} style={{ textAlign: 'center', marginTop: 12 }} />
          )}
        </>
      )}

      <Modal
        open={open}
        title={editing ? '编辑这一段婚姻' : '添加一段婚姻'}
        onCancel={() => setOpen(false)}
        onOk={save}
        destroyOnClose
      >
        <Form form={form} layout="vertical">
          <Form.Item name="spouse1_id" label="成员 A" rules={[{ required: true }]}>
            <PersonSelect excludeIds={spouse2 ? [spouse2] : []} />
          </Form.Item>
          <Form.Item name="spouse2_id" label="成员 B" rules={[{ required: true }]}>
            <PersonSelect excludeIds={spouse1 ? [spouse1] : []} />
          </Form.Item>
          <Form.Item
            name="marriage_order"
            label="本段次序"
            extra="按成员 A 的第几段婚姻填写；同一个 A 的次序不能重复"
          >
            <InputNumber min={1} />
          </Form.Item>
          <Space size={12} wrap>
            <Form.Item name="marriage_date" label="结婚日期">
              <DateInput />
            </Form.Item>
            <Form.Item name="divorce_date" label="离婚日期">
              <DateInput />
            </Form.Item>
          </Space>
          <Form.Item name="marriage_place" label="结婚地点">
            <Input />
          </Form.Item>
          <Form.Item name="description" label="说明">
            <Input.TextArea rows={2} />
          </Form.Item>
        </Form>
      </Modal>
    </Card>
  )
}
