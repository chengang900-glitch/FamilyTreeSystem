import { useEffect, useMemo, useState } from 'react'
import {
  Button, Card, Checkbox, Dropdown, Form, Input, InputNumber, Modal, Pagination, Popconfirm, Segmented, Select, Space, Table, Tag, message,
} from 'antd'
import { PlusOutlined, SearchOutlined } from '@ant-design/icons'
import { api } from '../api'
import { useStore } from '../store'
import { PERSON_TYPES } from '../constants'
import DateInput from '../components/DateInput'

const PERSON_TYPE_COLORS: Record<number, string> = {
  1: 'blue', 2: 'purple', 3: 'purple', 4: 'blue', 5: 'blue', 6: 'purple', 7: 'blue', 8: 'purple',
}

interface Row {
  id: number
  generation: number
  name: string
  courtesy_name: string
  art_name: string
  type: number
  birth_date: string
  death_date: string
  birth_place: string
  bury_address: string
  record: string
  notes: string
  branch_id: number | null
  branch_name: string
  address: string
  phone: string
  company: string
  position: string
}

export default function Persons() {
  const { user, familyId } = useStore()
  const fam = user?.families.find((f) => f.id === familyId)
  const writeable = !!fam && (fam.role === 'admin' || !!user?.is_superuser)
  const [rows, setRows] = useState<Row[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [view, setView] = useState<'table' | 'card'>(
    () => (localStorage.getItem('fts_person_view') === 'card' ? 'card' : 'table'))
  const [hiddenCols, setHiddenCols] = useState<string[]>(() => {
    try { return JSON.parse(localStorage.getItem('fts_person_cols') || '[]') } catch { return [] }
  })
  const size = Math.min(Math.max(user?.page_size || 20, 1), 500)
  const [kw, setKw] = useState('')
  const [gen, setGen] = useState<number | undefined>()
  const [type, setType] = useState<number | undefined>()
  const [branch, setBranch] = useState<number | undefined>()
  const [branches, setBranches] = useState<any[]>([])
  const [open, setOpen] = useState(false)
  const [editing, setEditing] = useState<Row | null>(null)
  const [form] = Form.useForm()
  const mobile = typeof window !== 'undefined' && window.innerWidth < 768

  const query = useMemo(
    () =>
      [
        `page=${page}`,
        `size=${size}`,
        kw ? `keyword=${encodeURIComponent(kw)}` : '',
        gen ? `generation=${gen}` : '',
        type ? `type=${type}` : '',
        branch ? `branch_id=${branch}` : '',
      ].filter(Boolean).join('&'),
    [page, size, kw, gen, type, branch],
  )

  const load = async () => {
    if (!familyId) return
    try {
      const data = await api.get(`/api/families/${familyId}/persons?${query}`)
      setRows(data.items)
      setTotal(data.total)
    } catch (e: any) {
      message.error(e.message)
    }
  }

  useEffect(() => {
    load()
  }, [familyId, query])

  useEffect(() => {
    // 筛选条件变化后回到第一页，避免停在超出结果集的页码
    setPage(1)
  }, [kw, gen, type, branch])

  useEffect(() => {
    if (familyId) api.get(`/api/families/${familyId}/branches`).then(setBranches).catch(() => {})
  }, [familyId])

  const save = async () => {
    const v = await form.validateFields()
    try {
      if (editing) {
        await api.put(`/api/families/${familyId}/persons/${editing.id}`, v)
      } else {
        await api.post(`/api/families/${familyId}/persons`, v)
      }
      message.success('已保存')
      setOpen(false)
      load()
    } catch (e: any) {
      message.error(e.message)
    }
  }

  const columns = [
    { key: 'generation', title: '世代', dataIndex: 'generation', width: 70 },
    { key: 'name', title: '姓名', dataIndex: 'name', width: 100 },
    { key: 'courtesy_name', title: '字', dataIndex: 'courtesy_name', width: 80 },
    { key: 'art_name', title: '号', dataIndex: 'art_name', width: 80 },
    {
      key: 'type',
      title: '类型',
      dataIndex: 'type',
      width: 80,
      render: (t: number) => (
        <Tag color={PERSON_TYPE_COLORS[t] || 'default'}>{PERSON_TYPES[t]}</Tag>
      ),
    },
    {
      key: 'life',
      title: '生卒',
      width: 190,
      render: (_: any, r: Row) => `${r.birth_date || '?'} ~ ${r.death_date || '在世'}`,
    },
    { key: 'branch', title: '所属分支', width: 120, ellipsis: true, render: (_: any, r: Row) => r.branch_name || '-' },
    { key: 'address', title: '住址', dataIndex: 'address', width: 150 },
    { key: 'phone', title: '手机号', dataIndex: 'phone', width: 150 },
    { key: 'company', title: '单位/公司', dataIndex: 'company', width: 150 },
    { key: 'position', title: '职位', dataIndex: 'position', width: 150 },

    {
      key: 'actions',
      title: '操作',
      width: 130,
      fixed: 'right' as const,
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
              title="确认删除该成员？"
              onConfirm={async () => {
                try {
                  await api.del(`/api/families/${familyId}/persons/${r.id}`)
                  message.success('已删除')
                  load()
                } catch (e: any) {
                  message.error(e.message)
                }
              }}
            >
              <Button size="small" danger>删除</Button>
            </Popconfirm>
          </Space>
        ) : (
          <Button
            size="small"
            onClick={() => {
              setEditing(r)
              form.setFieldsValue(r)
              setOpen(true)
            }}
          >
            查看
          </Button>
        ),
    },
  ]
  const visibleColumns = columns.filter((c) => !hiddenCols.includes(c.key))

  return (
    <Card
      title="成员管理"
      extra={
        writeable && (
          <Button
            type="primary"
            icon={<PlusOutlined />}
            onClick={() => {
              setEditing(null)
              form.resetFields()
              form.setFieldsValue({ generation: 1, type: 1 })
              setOpen(true)
            }}
          >
            添加成员
          </Button>
        )
      }
    >
      <Space wrap style={{ marginBottom: 12 }}>
        <Input
          allowClear
          prefix={<SearchOutlined />}
          placeholder="搜索姓名/字/号"
          style={{ width: 200 }}
          onPressEnter={(e: any) => setKw(e.target.value)}
          onChange={(e) => !e.target.value && setKw('')}
        />
        <Select
          allowClear
          placeholder="世代"
          style={{ width: 110 }}
          value={gen}
          onChange={setGen}
          options={Array.from({ length: 20 }, (_, i) => ({ value: i + 1, label: `第 ${i + 1} 世` }))}
        />
        <Select
          allowClear
          placeholder="类型"
          style={{ width: 110 }}
          value={type}
          onChange={setType}
          options={Object.entries(PERSON_TYPES).map(([k, v]) => ({ value: Number(k), label: v }))}
        />
        <Select
          allowClear
          placeholder="分支"
          style={{ width: 160 }}
          value={branch}
          onChange={setBranch}
          options={branches.map((b) => ({ value: b.id, label: b.name }))}
        />
        {!mobile && (
          <Segmented
            size="small"
            value={view}
            onChange={(v) => {
              const next = v as 'table' | 'card'
              setView(next)
              localStorage.setItem('fts_person_view', next)
            }}
            options={[{ value: 'table', label: '列表' }, { value: 'card', label: '卡片' }]}
          />
        )}
        {!mobile && view === 'table' && (
          <Dropdown
            menu={{
              selectable: true,
              multiple: true,
              selectedKeys: columns.filter((c) => !hiddenCols.includes(c.key)).map((c) => c.key),
              items: columns.map((c) => ({ key: c.key, label: c.title })),
              onClick: ({ key }) => {
                const next = hiddenCols.includes(key)
                  ? hiddenCols.filter((k) => k !== key)
                  : [...hiddenCols, key]
                setHiddenCols(next)
                localStorage.setItem('fts_person_cols', JSON.stringify(next))
              },
            }}
          >
            <Button size="small">列设置</Button>
          </Dropdown>
        )}
      </Space>

      {mobile || view === 'card' ? (
        <Space direction="vertical" style={{ width: '100%' }} size={8}>
          {rows.map((r) => (
            <Card key={r.id} size="small" styles={{ body: { padding: 12 } }}>
              <Space direction="vertical" size={2} style={{ width: '100%' }}>
                <Space>
                  <b>{r.name}</b>
                  <Tag color={PERSON_TYPE_COLORS[r.type] || 'default'}>{PERSON_TYPES[r.type]}</Tag>
                  <span style={{ color: '#888', fontSize: 12 }}>第{r.generation}世</span>
                </Space>
                <span style={{ fontSize: 12, color: '#666' }}>
                  {r.birth_date || '?'} ~ {r.death_date || '在世'}
                </span>
                <span style={{ fontSize: 12, color: '#888' }}>{r.branch_name || '未归分支'}</span>
                {r.address && <span style={{ fontSize: 12 }}>住址：{r.address}</span>}
                {r.phone && <span style={{ fontSize: 12 }}>手机号：{r.phone}</span>}
                {(r.company || r.position) && <span style={{ fontSize: 12 }}>{[r.company, r.position].filter(Boolean).join(' · ')}</span>}
                {writeable && (
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
                      title="确认删除？"
                      onConfirm={async () => {
                        await api.del(`/api/families/${familyId}/persons/${r.id}`)
                        load()
                      }}
                    >
                      <Button size="small" danger>删除</Button>
                    </Popconfirm>
                  </Space>
                )}
              </Space>
            </Card>
          ))}
          {rows.length === 0 && <div style={{ color: '#999', padding: 20 }}>暂无成员</div>}
          {total > size && (
            <Pagination
              simple
              current={page}
              pageSize={size}
              total={total}
              onChange={setPage}
              style={{ textAlign: 'center', marginTop: 8 }}
            />
          )}
        </Space>
      ) : (
        <Table
          rowKey="id"
          dataSource={rows}
          columns={visibleColumns}
          scroll={{ x: 1800 }}
          pagination={{
            current: page,
            pageSize: size,
            total,
            onChange: (p) => setPage(p),
            showTotal: (t) => `共 ${t} 位族人`,
          }}
        />
      )}

      <Modal
        open={open}
        title={editing ? '编辑成员' : '添加成员'}
        onCancel={() => setOpen(false)}
        onOk={save}
        width={640}
        destroyOnClose
        footer={writeable ? undefined : null}
      >
        <Form form={form} layout="vertical" disabled={!writeable}>
          <Space size={12} wrap>
            <Form.Item name="generation" label="世代" rules={[{ required: true }]}>
              <InputNumber min={1} max={99} />
            </Form.Item>
            <Form.Item name="name" label="姓名" rules={[{ required: true, message: '请输入姓名' }]}>
              <Input />
            </Form.Item>
            <Form.Item name="courtesy_name" label="字">
              <Input style={{ width: 96 }} />
            </Form.Item>
            <Form.Item name="art_name" label="号">
              <Input style={{ width: 96 }} />
            </Form.Item>
            <Form.Item name="type" label="成员类型">
              <Select
                style={{ width: 130 }}
                options={Object.entries(PERSON_TYPES).map(([k, v]) => ({ value: Number(k), label: v }))}
              />
            </Form.Item>
            <Form.Item name="branch_id" label="所属分支">
              <Select
                allowClear
                style={{ width: 356 }}
                options={branches.map((b) => ({ value: b.id, label: b.name }))}
              />
            </Form.Item>
          </Space>
          <Space size={12} wrap>
            <Form.Item name="birth_date" label="出生日期（公历/农历）">
              <DateInput />
            </Form.Item>
            <Form.Item name="death_date" label="逝世日期">
              <DateInput />
            </Form.Item>
          </Space>
          <Form.Item name="birth_place" label="出生地">
            <Input />
          </Form.Item>
          <Form.Item name="bury_address" label="安葬地点">
            <Input />
          </Form.Item>
          <Form.Item name="address" label="住址"><Input maxLength={1000} /></Form.Item>
          <Space wrap>
            <Form.Item name="phone" label="手机号"><Input type="tel" maxLength={50} /></Form.Item>
            <Form.Item name="company" label="单位/公司"><Input maxLength={200} /></Form.Item>
            <Form.Item name="position" label="职位"><Input maxLength={100} /></Form.Item>
          </Space>
          <Form.Item name="record" label="生平记事">
            <Input.TextArea rows={3} />
          </Form.Item>
          <Form.Item name="notes" label="备注">
            <Input.TextArea rows={2} />
          </Form.Item>
          <Form.Item name="is_private" valuePropName="checked">
            <Checkbox>仅家谱管理员/超管可见详情</Checkbox>
          </Form.Item>
        </Form>
      </Modal>
    </Card>
  )
}
