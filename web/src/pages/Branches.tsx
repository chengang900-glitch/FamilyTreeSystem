import { useEffect, useState } from 'react'
import {
  Button, Card, Checkbox, Form, Input, Modal, Popconfirm, Select, Space, Switch, Table, Tag, message,
} from 'antd'
import { PlusOutlined, TeamOutlined } from '@ant-design/icons'
import { api } from '../api'
import { useStore } from '../store'
import { PERSON_TYPES } from '../constants'

interface Row {
  id: number
  name: string
  parent_id: number | null
  hall_name: string
  generation_chars: string
  origin_place: string
  description: string
  person_count: number
}

export default function Branches() {
  const { user, familyId } = useStore()
  const fam = user?.families.find((f) => f.id === familyId)
  const writeable = !!fam && (fam.role === 'admin' || !!user?.is_superuser)
  const [rows, setRows] = useState<Row[]>([])
  const [people, setPeople] = useState<any[]>([])
  const [open, setOpen] = useState(false)
  const [editing, setEditing] = useState<Row | null>(null)
  const [form] = Form.useForm()
  const [selected, setSelected] = useState<number[]>([])
  const [filterType, setFilterType] = useState<number | undefined>()
  const [filterGen, setFilterGen] = useState<number | undefined>()
  const [memberModal, setMemberModal] = useState<Row | null>(null)
  const [memberIds, setMemberIds] = useState<number[]>([])

  const load = async () => {
    if (!familyId) return
    try {
      setRows(await api.get(`/api/families/${familyId}/branches`))
      const p = await api.get(`/api/families/${familyId}/persons?size=500`)
      setPeople(p.items)
    } catch (e: any) {
      message.error(e.message)
    }
  }

  useEffect(() => {
    load()
  }, [familyId])

  const openEdit = async (row: Row | null) => {
    setEditing(row)
    if (row) {
      const inBranch = people.filter((p) => p.branch_id === row.id).map((p) => p.id)
      setSelected(inBranch)
      form.setFieldsValue(row)
    } else {
      setSelected([])
      form.resetFields()
    }
    setOpen(true)
  }

  const save = async () => {
    const v = await form.validateFields()
    try {
      if (editing) {
        await api.put(`/api/families/${familyId}/branches/${editing.id}`, { ...v, person_ids: selected })
      } else {
        await api.post(`/api/families/${familyId}/branches`, { ...v, person_ids: selected })
      }
      message.success('已保存')
      setOpen(false)
      load()
    } catch (e: any) {
      message.error(e.message)
    }
  }

  const filtered = people.filter(
    (p) => (!filterType || p.type === filterType) && (!filterGen || p.generation === filterGen),
  )

  const openMembers = (row: Row) => {
    setMemberModal(row)
    setMemberIds(people.filter((p) => p.branch_id === row.id).map((p) => p.id))
  }

  const saveMembers = async () => {
    const before = people.filter((p) => p.branch_id === memberModal!.id).map((p) => p.id)
    const add = memberIds.filter((i) => !before.includes(i))
    const remove = before.filter((i) => !memberIds.includes(i))
    await api.post(`/api/families/${familyId}/branches/${memberModal!.id}/members`,
      { add_ids: add, remove_ids: remove })
    message.success('成员归属已更新')
    setMemberModal(null)
    load()
  }

  return (
    <Card
      title="分支房系"
      extra={
        writeable && (
          <Button type="primary" icon={<PlusOutlined />} onClick={() => openEdit(null)}>
            新建分支
          </Button>
        )
      }
    >
      <Table
        rowKey="id"
        dataSource={rows}
        scroll={{ x: 900 }}
        columns={[
          { title: '分支名称', dataIndex: 'name', width: 140 },
          {
            title: '上级分支',
            width: 120,
            render: (_: any, r: Row) => rows.find((b) => b.id === r.parent_id)?.name || '-',
          },
          { title: '堂号', dataIndex: 'hall_name', width: 110 },
          { title: '字辈', dataIndex: 'generation_chars', width: 140 },
          { title: '发源地', dataIndex: 'origin_place', width: 120 },
          { title: '人数', dataIndex: 'person_count', width: 80 },
          {
            title: '操作',
            width: 190,
            fixed: 'right',
            render: (_: any, r: Row) =>
              writeable ? (
                <Space size={4}>
                  <Button size="small" icon={<TeamOutlined />} onClick={() => openMembers(r)}>
                    成员
                  </Button>
                  <Button size="small" onClick={() => openEdit(r)}>编辑</Button>
                  <Popconfirm
                    title="删除后其成员将归为未分配，确认删除？"
                    onConfirm={async () => {
                      await api.del(`/api/families/${familyId}/branches/${r.id}`)
                      load()
                    }}
                  >
                    <Button size="small" danger>删除</Button>
                  </Popconfirm>
                </Space>
              ) : null,
          },
        ]}
      />

      <Modal
        open={open}
        title={editing ? '编辑分支' : '新建分支'}
        onCancel={() => setOpen(false)}
        onOk={save}
        width={760}
        destroyOnClose
      >
        <Form form={form} layout="vertical">
          <Space size={12} wrap>
            <Form.Item name="name" label="分支名称" rules={[{ required: true }]}>
              <Input />
            </Form.Item>
            <Form.Item name="parent_id" label="上级分支">
              <Select
                allowClear
                style={{ width: 160 }}
                options={rows
                  .filter((b) => !editing || b.id !== editing.id)
                  .map((b) => ({ value: b.id, label: b.name }))}
              />
            </Form.Item>
            <Form.Item name="hall_name" label="堂号">
              <Input />
            </Form.Item>
            <Form.Item name="generation_chars" label="字辈">
              <Input placeholder="如：木火土金水" />
            </Form.Item>
            <Form.Item name="origin_place" label="发源地">
              <Input />
            </Form.Item>
          </Space>
          <Form.Item name="description" label="家族训 / 简介">
            <Input.TextArea rows={2} />
          </Form.Item>
        </Form>

        <div style={{ marginTop: 8 }}>
          <Space wrap style={{ marginBottom: 8 }}>
            <b>分支成员（已选 {selected.length} 人）</b>
            <Select
              allowClear
              placeholder="按类型筛选"
              style={{ width: 120 }}
              value={filterType}
              onChange={setFilterType}
              options={Object.entries(PERSON_TYPES).map(([k, v]) => ({ value: Number(k), label: v }))}
            />
            <Select
              allowClear
              placeholder="按世代筛选"
              style={{ width: 120 }}
              value={filterGen}
              onChange={setFilterGen}
              options={Array.from({ length: 20 }, (_, i) => ({ value: i + 1, label: `第 ${i + 1} 世` }))}
            />
            <Button
              size="small"
              onClick={() => setSelected(Array.from(new Set([...selected, ...filtered.map((p) => p.id)])))}
            >
              全选
            </Button>
            <Button size="small" onClick={() => setSelected([])}>取消选中</Button>
          </Space>
          <Checkbox.Group
            style={{ width: '100%' }}
            value={selected}
            onChange={(v) => setSelected(v as number[])}
          >
            <div style={{ maxHeight: 240, overflow: 'auto', border: '1px solid #f0f0f0', padding: 8 }}>
              {filtered.map((p) => (
                <Checkbox key={p.id} value={p.id} style={{ margin: '2px 0', width: '33%' }}>
                  {p.name}
                  <Tag style={{ marginLeft: 4 }}>{PERSON_TYPES[p.type]}</Tag>
                </Checkbox>
              ))}
              {filtered.length === 0 && <div style={{ color: '#999' }}>暂无可选成员</div>}
            </div>
          </Checkbox.Group>
        </div>
      </Modal>

      <Modal
        open={!!memberModal}
        title={`批量归入 - ${memberModal?.name}`}
        onCancel={() => setMemberModal(null)}
        onOk={saveMembers}
        width={720}
        destroyOnClose
      >
        <Space wrap style={{ marginBottom: 8 }}>
          <Select
            allowClear
            placeholder="按类型筛选"
            style={{ width: 120 }}
            value={filterType}
            onChange={setFilterType}
            options={Object.entries(PERSON_TYPES).map(([k, v]) => ({ value: Number(k), label: v }))}
          />
          <Button
            size="small"
            onClick={() => setMemberIds(Array.from(new Set([...memberIds, ...filtered.map((p) => p.id)])))}
          >
            全选
          </Button>
          <Button size="small" onClick={() => setMemberIds([])}>取消选中</Button>
        </Space>
        <Checkbox.Group
          style={{ width: '100%' }}
          value={memberIds}
          onChange={(v) => setMemberIds(v as number[])}
        >
          <div style={{ maxHeight: 300, overflow: 'auto', border: '1px solid #f0f0f0', padding: 8 }}>
            {filtered.map((p) => (
              <Checkbox key={p.id} value={p.id} style={{ margin: '2px 0', width: '33%' }}>
                {p.name}（第{p.generation}世）
              </Checkbox>
            ))}
          </div>
        </Checkbox.Group>
      </Modal>
    </Card>
  )
}
