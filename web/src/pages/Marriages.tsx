import { useEffect, useState } from 'react'
import {
  Button, Card, Form, Input, InputNumber, Modal, Popconfirm, Select, Space, Table, message,
} from 'antd'
import { PlusOutlined } from '@ant-design/icons'
import { api } from '../api'
import { useStore } from '../store'

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
  const [people, setPeople] = useState<any[]>([])
  const [open, setOpen] = useState(false)
  const [editing, setEditing] = useState<Row | null>(null)
  const [form] = Form.useForm()

  const load = async () => {
    if (!familyId) return
    try {
      setRows(await api.get(`/api/families/${familyId}/marriages`))
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
    label: `第${p.generation}世 ${p.name}${p.courtesy_name ? '（' + p.courtesy_name + '）' : ''}`,
  }))

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
      title="婚姻管理"
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
            添加婚姻
          </Button>
        )
      }
    >
      <Table
        rowKey="id"
        dataSource={rows}
        scroll={{ x: 900 }}
        columns={[
          { title: '配偶一', dataIndex: 'spouse1_name', width: 120 },
          { title: '配偶二', dataIndex: 'spouse2_name', width: 120 },
          { title: '次序', dataIndex: 'marriage_order', width: 70 },
          { title: '结婚日期', dataIndex: 'marriage_date', width: 130 },
          { title: '离婚日期', dataIndex: 'divorce_date', width: 130 },
          { title: '地点', dataIndex: 'marriage_place', width: 140 },
          { title: '说明', dataIndex: 'description' },
          {
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
        ]}
      />

      <Modal
        open={open}
        title={editing ? '编辑婚姻' : '添加婚姻'}
        onCancel={() => setOpen(false)}
        onOk={save}
        destroyOnClose
      >
        <Form form={form} layout="vertical">
          <Form.Item name="spouse1_id" label="配偶一" rules={[{ required: true }]}>
            <Select showSearch optionFilterProp="label" options={personOptions} />
          </Form.Item>
          <Form.Item name="spouse2_id" label="配偶二" rules={[{ required: true }]}>
            <Select showSearch optionFilterProp="label" options={personOptions} />
          </Form.Item>
          <Space size={12} wrap>
            <Form.Item name="marriage_order" label="婚姻次序">
              <InputNumber min={1} />
            </Form.Item>
            <Form.Item name="marriage_date" label="结婚日期">
              <Input />
            </Form.Item>
            <Form.Item name="divorce_date" label="离婚日期">
              <Input />
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
