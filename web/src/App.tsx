import { useEffect, type ReactElement } from 'react'
import { Navigate, Route, Routes, useLocation } from 'react-router-dom'
import { Spin } from 'antd'
import { useStore } from './store'
import Login from './pages/Login'
import AppLayout from './layout/AppLayout'
import Home from './pages/Home'
import Profile from './pages/Profile'
import Users from './pages/admin/Users'
import Families from './pages/admin/Families'
import Settings from './pages/admin/Settings'
import Logs from './pages/admin/Logs'
import Persons from './pages/Persons'
import Marriages from './pages/Marriages'
import ParentChild from './pages/ParentChild'
import Branches from './pages/Branches'
import Events from './pages/Events'
import Resources from './pages/Resources'
import Pedigree from './pages/Pedigree'
import DataExchange from './pages/DataExchange'
import PrintBook from './pages/PrintBook'
import FamilyMembers from './pages/FamilyMembers'

function Guard({ children, admin }: { children: ReactElement; admin?: boolean }) {
  const { user, loaded } = useStore()
  const loc = useLocation()
  if (!loaded) return <div style={{ padding: 80, textAlign: 'center' }}><Spin size="large" /></div>
  if (!user) return <Navigate to="/login" state={{ from: loc.pathname }} replace />
  if (admin && !user.is_superuser) return <Navigate to="/" replace />
  return children
}

export default function App() {
  const load = useStore((s) => s.load)
  useEffect(() => {
    load()
  }, [load])

  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route
        element={
          <Guard>
            <AppLayout />
          </Guard>
        }
      >
        <Route path="/" element={<Home />} />
        <Route path="/profile" element={<Profile />} />
        <Route path="/persons" element={<Persons />} />
        <Route path="/marriages" element={<Marriages />} />
        <Route path="/parentchild" element={<ParentChild />} />
        <Route path="/branches" element={<Branches />} />
        <Route path="/events" element={<Events />} />
        <Route path="/resources" element={<Resources />} />
        <Route path="/pedigree" element={<Pedigree />} />
        <Route path="/exchange" element={<DataExchange />} />
        <Route path="/print" element={<PrintBook />} />
        <Route path="/members" element={<FamilyMembers />} />
      </Route>
      <Route
        element={
          <Guard admin>
            <AppLayout />
          </Guard>
        }
      >
        <Route path="/admin/users" element={<Users />} />
        <Route path="/admin/families" element={<Families />} />
        <Route path="/admin/settings" element={<Settings />} />
        <Route path="/admin/logs" element={<Logs />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
