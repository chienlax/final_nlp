/**
 * Main App Component
 * 
 * Simplified layout for 3-zone workbench:
 * - No Container wrapper (workbench needs full viewport)
 * - Minimal top bar for user selection only
 * - Full-height workbench below
 */

import { useState, useEffect } from 'react'
import {
    Box,
    Select,
    MenuItem,
    FormControl,
    CircularProgress,
    Alert,
    Typography,
    Avatar,
    Chip,
} from '@mui/material'
import { Person } from '@mui/icons-material'
import { useQuery } from '@tanstack/react-query'
import axios from 'axios'
import { WorkbenchPage } from './pages/WorkbenchPage'

// Types
interface User {
    id: number
    username: string
    role: string
}

// API base
const api = axios.create({
    baseURL: '/api',
})

function App() {
    const [selectedUserId, setSelectedUserId] = useState<number | null>(null)

    // Fetch users
    const { data: users, isLoading, error } = useQuery<User[]>({
        queryKey: ['users'],
        queryFn: () => api.get('/users').then(res => res.data),
    })

    // Set default user on load
    useEffect(() => {
        if (users && users.length > 0 && !selectedUserId) {
            setSelectedUserId(users[0].id)
        }
    }, [users, selectedUserId])

    // Configure axios default header
    useEffect(() => {
        if (selectedUserId) {
            api.defaults.headers.common['X-User-ID'] = selectedUserId.toString()
        }
    }, [selectedUserId])

    const selectedUser = users?.find(u => u.id === selectedUserId)

    // Loading state
    if (isLoading) {
        return (
            <Box
                sx={{
                    height: '100vh',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    flexDirection: 'column',
                    gap: 2,
                    background: 'linear-gradient(135deg, #0a1929 0%, #1a2f4a 100%)',
                }}
            >
                <CircularProgress size={48} />
                <Typography>Loading application...</Typography>
            </Box>
        )
    }

    // Error state
    if (error) {
        return (
            <Box
                sx={{
                    height: '100vh',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    background: 'linear-gradient(135deg, #0a1929 0%, #1a2f4a 100%)',
                    p: 4,
                }}
            >
                <Alert severity="error" sx={{ maxWidth: 500 }}>
                    <Typography variant="h6" gutterBottom>Connection Error</Typography>
                    <Typography>
                        Failed to connect to the backend API. Please ensure the FastAPI server
                        is running on port 8000.
                    </Typography>
                </Alert>
            </Box>
        )
    }

    // No user selected
    if (!selectedUserId) {
        return (
            <Box
                sx={{
                    height: '100vh',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    flexDirection: 'column',
                    gap: 3,
                    background: 'linear-gradient(135deg, #0a1929 0%, #1a2f4a 100%)',
                }}
            >
                <Typography variant="h4" gutterBottom>
                    🎙️ Speech Translation Workbench
                </Typography>
                <Typography color="text.secondary" sx={{ mb: 2 }}>
                    Select your user profile to begin annotating
                </Typography>

                <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 2, justifyContent: 'center' }}>
                    {users?.map(user => (
                        <Box
                            key={user.id}
                            onClick={() => setSelectedUserId(user.id)}
                            sx={{
                                display: 'flex',
                                flexDirection: 'column',
                                alignItems: 'center',
                                gap: 1,
                                p: 3,
                                borderRadius: 2,
                                bgcolor: 'rgba(255,255,255,0.05)',
                                border: '1px solid rgba(255,255,255,0.1)',
                                cursor: 'pointer',
                                transition: 'all 0.2s',
                                minWidth: 120,
                                '&:hover': {
                                    bgcolor: 'rgba(255,255,255,0.1)',
                                    transform: 'translateY(-2px)',
                                }
                            }}
                        >
                            <Avatar sx={{ width: 56, height: 56, bgcolor: 'primary.main' }}>
                                <Person />
                            </Avatar>
                            <Typography fontWeight={600}>{user.username}</Typography>
                            <Chip
                                label={user.role}
                                size="small"
                                color={user.role === 'admin' ? 'error' : 'default'}
                            />
                        </Box>
                    ))}
                </Box>
            </Box>
        )
    }

    // Main app with workbench
    return (
        <Box sx={{ height: '100vh', display: 'flex', flexDirection: 'column' }}>
            {/* Minimal top bar */}
            <Box
                sx={{
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    px: 2,
                    py: 1,
                    bgcolor: 'rgba(0,0,0,0.3)',
                    borderBottom: '1px solid rgba(255,255,255,0.1)',
                }}
            >
                <Typography variant="h6" sx={{ fontWeight: 600, fontSize: 16 }}>
                    🎙️ Speech Translation Workbench
                </Typography>

                <Box sx={{ display: 'flex', alignItems: 'center', gap: 2 }}>
                    <FormControl size="small" sx={{ minWidth: 140 }}>
                        <Select
                            value={selectedUserId}
                            onChange={(e) => setSelectedUserId(Number(e.target.value))}
                            size="small"
                            sx={{ bgcolor: 'rgba(255,255,255,0.05)' }}
                        >
                            {users?.map(user => (
                                <MenuItem key={user.id} value={user.id}>
                                    {user.username}
                                </MenuItem>
                            ))}
                        </Select>
                    </FormControl>

                    {selectedUser && (
                        <Chip
                            label={selectedUser.role}
                            size="small"
                            color={selectedUser.role === 'admin' ? 'error' : 'default'}
                        />
                    )}
                </Box>
            </Box>

            {/* Full-height workbench */}
            <Box sx={{ flex: 1, minHeight: 0 }}>
                <WorkbenchPage
                    userId={selectedUserId}
                    username={selectedUser?.username || 'User'}
                />
            </Box>
        </Box>
    )
}

export default App
