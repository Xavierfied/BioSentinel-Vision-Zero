import { BrowserRouter, Routes, Route, Navigate }
  from 'react-router-dom'
import { AuthProvider } from './context/AuthContext'
import ProtectedRoute from './components/ProtectedRoute'
import Enroll    from './pages/Enroll'
import Login     from './pages/Login'
import Dashboard from './pages/Dashboard'
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
