import { useEffect, useState } from 'react'
import {
  Button, Card, Form, Input, Modal, Popconfirm, Select, Space, Table, Tag, message,
} from 'antd'
import { PlusOutlined } from '@ant-design/icons'
import { api } from '../api'
import { useStore } from '../store'
import { PC_TYPES } from '../constants'

interface Row {
  id: number
  parent_id: number
  child_id: number
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
  const [people, setPeople] = useState<any[]>([])
  const [open, setOpen] = useState(false)
  const [form] = Form.useForm()

  const load = async () => {
    if (!familyId) return
    try {
      setRows(await api.get(`/api/families/${familyId}/parentchild`))
      const p = await api.get(`/api/families/${familyId}/persons?size=200`)
      setPeople(p.items)
    } catch (e: any) {
      message.error(e.message)
    }
  }

  useEffect(() => {
    load()
  }, [familyId])

  const personOptions = people.map((p) => ({
    value: p.id,
    label: `第${p.generation}世 ${p.name}`,
  }))

  const save = async () => {
    const v = await form.validateFields()
    try {
      await api.post(`/api/families/${familyId}/parentchild`, v)
      message.success('已登记')
      setOpen(false)
      load()
    } catch (e: any) {
      message.error(e.message)
    }
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
              form.setFieldsValue({ type: 1 })
              setOpen(true)
            }}
          >
            添加亲子
          </Button>
        )
      }
    >
      <Table
        rowKey="id"
        dataSource={rows}
        scroll={{ x: 800 }}
        columns={[
          { title: '父/母', dataIndex: 'parent_name', width: 140 },
          { title: '子女', dataIndex: 'child_name', width: 140 },
          {
            title: '关系类型',
            dataIndex: 'type',
            width: 100,
            render: (t: number) => <Tag>{PC_TYPES[t]}</Tag>,
          },
          { title: '说明', dataIndex: 'description' },
          {
            title: '操作',
            width: 80,
            render: (_: any, r: Row) =>
              writeable ? (
                <Popconfirm
                  title="确认删除该亲子关系？"
                  onConfirm={async () => {
                    await api.del(`/api/families/${familyId}/parentchild/${r.id}`)
                    load()
                  }}
                >
                  <Button size="small" danger>删除</Button>
                </Popconfirm>
              ) : null,
          },
        ]}
      />

      <Modal open={open} title="添加亲子关系" onCancel={() => setOpen(false)} onOk={save} destroyOnClose>
        <Form form={form} layout="vertical">
          <Form.Item name="parent_id" label="父/母" rules={[{ required: true }]}>
            <Select showSearch optionFilterProp="label" options={personOptions} />
          </Form.Item>
          <Form.Item
            name="child_ids"
            label="子女（可多选，一次登记多名）"
            rules={[{ required: true, message: '请选择至少一名子女' }]}
          >
            <Select mode="multiple" showSearch optionFilterProp="label" options={personOptions} />
          </Form.Item>
          <Form.Item name="type" label="与父/母的生养关系">
            <Select options={Object.entries(PC_TYPES).map(([k, v]) => ({ value: Number(k), label: v }))} />
          </Form.Item>
          <Form.Item name="description" label="说明">
            <Input.TextArea rows={2} />
          </Form.Item>
        </Form>
      </Modal>
    </Card>
  )
}
