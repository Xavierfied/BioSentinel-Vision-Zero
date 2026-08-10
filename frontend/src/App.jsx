import { BrowserRouter, Routes, Route, Navigate }
  from 'react-router-dom'
import { AuthProvider } from './context/AuthContext'
import ProtectedRoute from './components/ProtectedRoute'
import Enroll    from './pages/Enroll'
import Login     from './pages/Login'
import Dashboard from './pages/Dashboard'
import DemoLanding  from './pages/demo/DemoLanding'
import DemoEnroll   from './pages/demo/DemoEnroll'
import DemoLogin    from './pages/demo/DemoLogin'
import DemoSession  from './pages/demo/DemoSession'
import DemoAttack   from './pages/demo/DemoAttack'
import DemoAdmin    from './pages/demo/DemoAdmin'
import './styles/global.css'

export default function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/"        element={
            <Navigate to="/login" replace />} />
          <Route path="/enroll"  element={<Enroll />} />
          <Route path="/login"   element={<Login />} />
          <Route path="/demo"         element={<DemoLanding />} />
          <Route path="/demo/enroll"  element={<DemoEnroll />} />
          <Route path="/demo/login"   element={<DemoLogin />} />
          <Route path="/demo/session" element={<DemoSession />} />
          <Route path="/demo/attack"  element={<DemoAttack />} />
          <Route path="/demo/admin"   element={<DemoAdmin />} />
          <Route path="/dashboard" element={
            <ProtectedRoute>
              <Dashboard />
            </ProtectedRoute>
          } />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  )
}
