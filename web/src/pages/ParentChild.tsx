import { useEffect, useState } from 'react'
import {
  Button, Card, Form, Input, InputNumber, Modal, Pagination, Popconfirm, Segmented, Select, Space, Table, Tag, message,
} from 'antd'
import { MinusCircleOutlined, PlusOutlined } from '@ant-design/icons'
import { api } from '../api'
import { useStore } from '../store'
import PersonSelect from '../components/PersonSelect'
import ColumnSettings, { useColumnSettings } from '../components/ColumnSettings'
import { PC_TYPES } from '../constants'

interface Row {
  id: number
  parent_id: number
  child_id: number
  parent_type: number
  child_order: number | null
  parent_name: string
  child_name: string
  type: number
  description: string
}

export default function ParentChild() {
  const { user, familyId } = useStore()
  const fam = user?.families.find((f) => f.id === familyId)
  const writeable = !!fam && (fam.role === 'admin' || !!user?.is_superuser)
  const [rows, setRows] = useState<Row[]>([])
  const [page, setPage] = useState(1)
  const [total, setTotal] = useState(0)
  const size = user?.page_size || 50
  const [view, setView] = useState<'table' | 'card'>(
    () => (localStorage.getItem('fts_parentchild_view') === 'card' ? 'card' : 'table'))
  const cols = useColumnSettings<any>('fts_parentchild_cols')
  const columnMeta = [
    { key: 'parent_name', title: '父/母' },
    { key: 'child_name', title: '子女' },
    { key: 'type', title: '关系类型' },
    { key: 'child_order', title: '排行' },
    { key: 'description', title: '说明' },
    { key: 'actions', title: '操作' },
  ]
  const [open, setOpen] = useState(false)
  const [form] = Form.useForm()
  const [editing, setEditing] = useState<Row | null>(null)
  const [editForm] = Form.useForm()
  const editRole = Form.useWatch('parent_role', editForm)
  const father = Form.useWatch('father_id', form)
  const mother = Form.useWatch('mother_id', form)

  const load = async () => {
    if (!familyId) return
    try {
      const d = await api.get(`/api/families/${familyId}/parentchild?page=${page}&size=${size}`)
      setRows(d.items)
      setTotal(d.total)
    } catch (e: any) {
      message.error(e.message)
    }
  }

  useEffect(() => {
    load()
  }, [familyId, page, size])

  const save = async () => {
    const v = await form.validateFields()
    if (!v.father_id && !v.mother_id) {
      message.warning('请至少选择父亲或母亲一方')
      return
    }
    try {
      await api.post(`/api/families/${familyId}/parentchild`, v)
      message.success('已登记')
      setOpen(false)
      load()
    } catch (e: any) {
      message.error(e.message)
    }
  }

  const edit = (r: Row) => {
    editForm.resetFields()
    editForm.setFieldsValue({ ...r, parent_role: [1, 4, 5, 7].includes(r.parent_type) ? 'father' : 'mother' })
    setEditing(r)
  }
  const saveEdit = async () => {
    const v = await editForm.validateFields()
    try {
      await api.put(`/api/families/${familyId}/parentchild/${editing!.id}`, { ...v, child_order: v.child_order ?? null })
      message.success('已保存'); setEditing(null); load()
    } catch (e: any) { message.error(e.message) }
  }

  return (
    <Card
      title="亲子关系"
      extra={
        writeable && (
          <Button
            type="primary"
            icon={<PlusOutlined />}
            onClick={() => {
              form.resetFields()
              form.setFieldsValue({ children: [{ father_type: 1, mother_type: 1 }] })
              setOpen(true)
            }}
          >
            添加亲子
          </Button>
        )
      }
    >
      <Space wrap style={{ marginBottom: 12 }}>
        <ColumnSettings columns={columnMeta} hidden={cols.hidden} onToggle={cols.toggle} />
        <Segmented
          size="small"
          value={view}
          onChange={(v) => {
            const next = v as 'table' | 'card'
            setView(next)
            localStorage.setItem('fts_parentchild_view', next)
          }}
          options={[{ value: 'table', label: '列表' }, { value: 'card', label: '卡片' }]}
        />
      </Space>
      {view === 'table' ? (
      <Table
        rowKey="id"
        dataSource={rows}
        pagination={{ current: page, pageSize: size, total, onChange: setPage, showSizeChanger: false }}
        scroll={{ x: 800 }}
        columns={cols.visible([
          { key: 'parent_name', title: '父/母', dataIndex: 'parent_name', width: 140 },
          { key: 'child_name', title: '子女', dataIndex: 'child_name', width: 140 },
          {
            key: 'type',
            title: '关系类型',
            dataIndex: 'type',
            width: 100,
            render: (t: number) => <Tag>{PC_TYPES[t]}</Tag>,
          },
          { key: 'child_order', title: '排行', dataIndex: 'child_order', width: 90, render: (n: number | null) => n ? `第 ${n}` : '未确认' },
          { key: 'description', title: '说明', dataIndex: 'description' },
          {
            key: 'actions',
            title: '操作',
            width: 150,
            render: (_: any, r: Row) =>
              writeable ? (
                <Space><Button size="small" onClick={() => edit(r)}>编辑</Button><Popconfirm
                  title="确认删除该亲子关系？"
                  onConfirm={async () => {
                    await api.del(`/api/families/${familyId}/parentchild/${r.id}`)
                    load()
                  }}
                >
                  <Button size="small" danger>删除</Button>
                </Popconfirm></Space>
              ) : null,
          },
        ])}
      />
      ) : (
        <>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill,minmax(280px,1fr))', gap: 12 }}>
            {rows.map((r) => (
              <Card key={r.id} size="small" title={`${r.parent_name} → ${r.child_name}`}
                extra={<Tag>{PC_TYPES[r.type]}</Tag>}>
                <Space direction="vertical" size={4} style={{ width: '100%' }}>
                  <span>排行：{r.child_order ? `第 ${r.child_order}` : '未确认'}</span>
                  <span style={{ fontSize: 13 }}>{r.description || '无说明'}</span>
                  {writeable && (
                    <Space><Button size="small" onClick={() => edit(r)}>编辑</Button><Popconfirm title="确认删除该亲子关系？"
                      onConfirm={async () => {
                        await api.del(`/api/families/${familyId}/parentchild/${r.id}`)
                        load()
                      }}>
                      <Button size="small" danger>删除</Button>
                    </Popconfirm></Space>
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

      <p style={{ color: '#777', fontSize: 12 }}>列表按父母世代升序排列，同一位父/母连续显示，子女按出生日期由早到晚排序；仅知年/月的按已知信息排序，日期不详的放在组末。男女统一排行，由人工确认，列表排序不修改排行。</p>
      <Modal open={!!editing} title="编辑亲子关系" onCancel={() => setEditing(null)} onOk={saveEdit} forceRender>
        <Form form={editForm} layout="vertical">
          <Form.Item name="parent_role" label="父/母身份" rules={[{ required: true }]}>
            <Select onChange={() => editForm.setFieldValue('parent_id', undefined)} options={[{ value: 'father', label: '父亲' }, { value: 'mother', label: '母亲' }]} />
          </Form.Item>
          <Form.Item name="parent_id" label="父/母成员" rules={[{ required: true, message: '请选择父/母成员' }]}>
            <PersonSelect allowedTypes={editRole === 'father' ? [1, 4, 5, 7] : [2, 3, 6, 8]} style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="child_id" label="子女" rules={[{ required: true, message: '请选择子女' }]}><PersonSelect style={{ width: '100%' }} /></Form.Item>
          <Form.Item name="type" label="关系类型" rules={[{ required: true }]}><Select options={Object.entries(PC_TYPES).map(([k, v]) => ({ value: Number(k), label: v }))} /></Form.Item>
          <Form.Item name="child_order" label="子女排行（人工确认，可留空）"><InputNumber min={1} max={9999} precision={0} placeholder="未确认" style={{ width: '100%' }} /></Form.Item>
          <Form.Item name="description" label="说明"><Input.TextArea rows={2} /></Form.Item>
        </Form>
        <p style={{ color: '#777' }}>仅编辑当前这一条父/母与子女的关系，另一方关系保留。排行按当前父/母名下全部子女核对，男女统一。</p>
      </Modal>
      <Modal open={open} title="登记父母与子女" width={760} onCancel={() => setOpen(false)} onOk={save} destroyOnClose>
        <Form form={form} layout="vertical">
          <Space wrap align="start">
            <Form.Item name="father_id" label="父亲（父母至少选择一方）"><PersonSelect allowedTypes={[1, 4, 5, 7]} excludeIds={mother ? [mother] : []} placeholder="选择宗男、姻婿、外孙或其他（男）" style={{ width: 280 }} /></Form.Item>
            <Form.Item name="mother_id" label="母亲"><PersonSelect allowedTypes={[2, 3, 6, 8]} excludeIds={father ? [father] : []} placeholder="选择宗女、姻媳、外孙女或其他（女）" style={{ width: 280 }} /></Form.Item>
          </Space>
          <p>请为本批子女选择对应父母；再婚家庭中，不同母亲的子女请分批登记。身份不详时可留空一方。</p>
          <Form.List name="children" rules={[{ validator: async (_, rows) => {
            if (!rows?.length) throw new Error('请至少添加一名子女')
          } }]}>
            {(fields, { add, remove }, { errors }) => <>
              {fields.map(({ key, name, ...rest }) => (
                <Space key={key} wrap align="start">
                  <Form.Item {...rest} name={[name, 'child_id']} label="子女" rules={[{ required: true, message: '请选择子女' }]}>
                    <PersonSelect excludeIds={[father, mother].filter(Boolean)} style={{ width: 240 }} />
                  </Form.Item>
                  <Form.Item {...rest} name={[name, 'father_type']} label="与父亲关系">
                    <Select style={{ width: 130 }} options={Object.entries(PC_TYPES).map(([k, v]) => ({ value: Number(k), label: v }))} />
                  </Form.Item>
                  <Form.Item {...rest} name={[name, 'mother_type']} label="与母亲关系">
                    <Select style={{ width: 130 }} options={Object.entries(PC_TYPES).map(([k, v]) => ({ value: Number(k), label: v }))} />
                  </Form.Item>
                  <Form.Item {...rest} name={[name, 'child_order']} label="排行（可留空）">
                    <InputNumber min={1} max={9999} precision={0} placeholder="未确认" style={{ width: 110 }} />
                  </Form.Item>
                  <Button style={{ marginTop: 30 }} aria-label="移除子女" icon={<MinusCircleOutlined />} onClick={() => remove(name)} />
                </Space>
              ))}
              <Button icon={<PlusOutlined />} onClick={() => add({ father_type: 1, mother_type: 1 })}>添加一名子女</Button>
              <Form.ErrorList errors={errors} />
            </>}
          </Form.List>
          <p style={{ color: '#888' }}>已存在的亲子关系会更新为本次选择的类型；所有关系一次保存。</p>
          <Form.Item name="description" label="说明">
            <Input.TextArea rows={2} />
          </Form.Item>
        </Form>
      </Modal>
    </Card>
  )
}
