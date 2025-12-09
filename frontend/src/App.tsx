import { useState, useEffect } from 'react'
import {
    Box,
    AppBar,
    Toolbar,
    Typography,
    Container,
    Select,
    MenuItem,
    FormControl,
    InputLabel,
    CircularProgress,
    Alert,
    Button,
    Chip
} from '@mui/material'
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

    return (
        <Box sx={{ display: 'flex', flexDirection: 'column', minHeight: '100vh' }}>
            {/* Header */}
            <AppBar position="static" elevation={0} sx={{ bgcolor: 'background.paper' }}>
                <Toolbar>
                    <Typography variant="h6" sx={{ flexGrow: 1, fontWeight: 600 }}>
                        🎙️ Speech Translation Workbench
                    </Typography>

                    {/* User selector */}
                    <FormControl size="small" sx={{ minWidth: 150, mr: 2 }}>
                        <InputLabel>User</InputLabel>
                        <Select
                            value={selectedUserId || ''}
                            label="User"
                            onChange={(e) => setSelectedUserId(Number(e.target.value))}
                            disabled={isLoading}
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
                </Toolbar>
            </AppBar>

            {/* Main content */}
            <Container maxWidth="xl" sx={{ flexGrow: 1, py: 3 }}>
                {isLoading && (
                    <Box display="flex" justifyContent="center" py={4}>
                        <CircularProgress />
                    </Box>
                )}

                {error && (
                    <Alert severity="error" sx={{ mb: 2 }}>
                        Failed to load users. Is the backend running on port 8000?
                    </Alert>
                )}

                {!selectedUserId && !isLoading && (
                    <Alert severity="info">
                        Please select a user to continue
                    </Alert>
                )}

                {selectedUserId && (
                    <WorkbenchPage userId={selectedUserId} />
                )}
            </Container>

            {/* Footer */}
            <Box sx={{ p: 2, textAlign: 'center', color: 'text.secondary', fontSize: 12 }}>
                Vietnamese-English Code-Switching Speech Translation Pipeline v2.0
            </Box>
        </Box>
    )
}

export default App
