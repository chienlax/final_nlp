/**
 * Main App Component - 5-Tab Navigation System
 * 
 * Tabs:
 * 1. Dashboard - Channel overview (gemini_ui_1)
 * 2. Channel - Video list (gemini_ui_2) - Dynamic, appears when channel selected
 * 3. Annotation - Workbench (gemini_ui_3, gemini_ui_4)
 * 4. Processing - Denoise queue (gemini_ui_5)
 * 5. Export - Export wizard (gemini_ui_7)
 * 6. Settings - User/system config
 */

import { useState, useEffect } from 'react'
import {
    Box,
    Tabs,
    Tab,
    Select,
    MenuItem,
    FormControl,
    CircularProgress,
    Alert,
    Typography,
    Avatar,
    Chip,
} from '@mui/material'
import {
    Dashboard as DashboardIcon,
    VideoLibrary as ChannelIcon,
    Edit as AnnotationIcon,
    Tune as ProcessingIcon,
    FileDownload as ExportIcon,
    Settings as SettingsIcon,
    Person,
} from '@mui/icons-material'
import { useQuery } from '@tanstack/react-query'
import axios from 'axios'

// Page imports
import { DashboardPage } from './pages/DashboardPage'
import { ChannelPage } from './pages/ChannelPage'
import { WorkbenchPage } from './pages/WorkbenchPage'
import { ProcessingPage } from './pages/ProcessingPage'
import { ExportPage } from './pages/ExportPage'
import { SettingsPage } from './pages/SettingsPage'

// Types
interface User {
    id: number
    username: string
    role: string
}

interface Channel {
    id: number
    name: string
    url: string
}

// Tab configuration
type TabId = 'dashboard' | 'channel' | 'annotation' | 'processing' | 'export' | 'settings'

interface TabConfig {
    id: TabId
    label: string
    icon: React.ReactElement
    dynamic?: boolean  // If true, only shows when condition is met
}

const TABS: TabConfig[] = [
    { id: 'dashboard', label: 'Dashboard', icon: <DashboardIcon /> },
    { id: 'channel', label: 'Channel', icon: <ChannelIcon />, dynamic: true },
    { id: 'annotation', label: 'Annotation', icon: <AnnotationIcon /> },
    { id: 'processing', label: 'Processing', icon: <ProcessingIcon /> },
    { id: 'export', label: 'Export', icon: <ExportIcon /> },
    { id: 'settings', label: 'Settings', icon: <SettingsIcon /> },
]

// API base
const api = axios.create({
    baseURL: '/api',
})

function App() {
    const [selectedUserId, setSelectedUserId] = useState<number | null>(null)
    const [currentTab, setCurrentTab] = useState<TabId>('dashboard')
    const [selectedChannel, setSelectedChannel] = useState<Channel | null>(null)
    const [selectedVideoId, setSelectedVideoId] = useState<number | null>(null)
    const [selectedChunkId, setSelectedChunkId] = useState<number | null>(null)

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

    // Navigation handlers
    const handleChannelSelect = (channel: Channel) => {
        setSelectedChannel(channel)
        setCurrentTab('channel')
    }

    const handleVideoSelect = (videoId: number, chunkId?: number) => {
        setSelectedVideoId(videoId)
        if (chunkId) setSelectedChunkId(chunkId)
        setCurrentTab('annotation')
    }

    const handleTabChange = (_: React.SyntheticEvent, newValue: TabId) => {
        // If switching away from channel tab, clear channel selection
        if (newValue !== 'channel') {
            // Keep channel in case user wants to go back
        }
        setCurrentTab(newValue)
    }

    // Get visible tabs (filter out dynamic tabs when not active)
    const visibleTabs = TABS.filter(tab => {
        if (tab.dynamic && tab.id === 'channel') {
            return selectedChannel !== null
        }
        return !tab.dynamic
    })

    // Loading state
    if (isLoading) {
        return (
            <Box className="app-loading">
                <CircularProgress size={48} />
                <Typography>Loading application...</Typography>
            </Box>
        )
    }

    // Error state
    if (error) {
        return (
            <Box className="app-error">
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

    // No user selected - User Selection Screen (gemini_ui_6)
    if (!selectedUserId) {
        return (
            <Box className="user-selection-screen">
                <Typography variant="h4" gutterBottom>
                    🎙️ Speech Translation Workbench
                </Typography>
                <Typography color="text.secondary" sx={{ mb: 3 }}>
                    Select your user profile to begin
                </Typography>

                <Box className="user-cards">
                    {users?.map(user => (
                        <Box
                            key={user.id}
                            className="user-card"
                            onClick={() => setSelectedUserId(user.id)}
                        >
                            <Avatar sx={{ width: 64, height: 64, bgcolor: 'primary.main' }}>
                                <Person sx={{ fontSize: 32 }} />
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

    // Main app with tab navigation
    return (
        <Box className="app-container">
            {/* Header with tabs and user selector */}
            <Box className="app-header">
                <Box className="header-left">
                    <Typography variant="h6" className="app-title">
                        🎙️ Speech Translation
                    </Typography>
                </Box>

                <Box className="header-tabs">
                    <Tabs
                        value={currentTab}
                        onChange={handleTabChange}
                        textColor="inherit"
                        TabIndicatorProps={{
                            style: { backgroundColor: '#90caf9', height: 3 }
                        }}
                    >
                        {visibleTabs.map(tab => (
                            <Tab
                                key={tab.id}
                                value={tab.id}
                                icon={tab.icon}
                                iconPosition="start"
                                label={tab.id === 'channel' && selectedChannel
                                    ? selectedChannel.name
                                    : tab.label
                                }
                                sx={{
                                    minHeight: 56,
                                    textTransform: 'none',
                                    fontSize: 14,
                                    fontWeight: 500,
                                    gap: 0.5,
                                }}
                            />
                        ))}
                    </Tabs>
                </Box>

                <Box className="header-right">
                    <FormControl size="small" sx={{ minWidth: 120 }}>
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

            {/* Tab content area */}
            <Box className="app-content">
                {currentTab === 'dashboard' && (
                    <DashboardPage
                        userId={selectedUserId}
                        onChannelSelect={handleChannelSelect}
                    />
                )}

                {currentTab === 'channel' && selectedChannel && (
                    <ChannelPage
                        userId={selectedUserId}
                        channel={selectedChannel}
                        onVideoSelect={handleVideoSelect}
                        onBack={() => setCurrentTab('dashboard')}
                    />
                )}

                {currentTab === 'annotation' && (
                    <WorkbenchPage
                        userId={selectedUserId}
                        username={selectedUser?.username || 'User'}
                        preselectedVideoId={selectedVideoId}
                        preselectedChunkId={selectedChunkId}
                    />
                )}

                {currentTab === 'processing' && (
                    <ProcessingPage userId={selectedUserId} />
                )}

                {currentTab === 'export' && (
                    <ExportPage userId={selectedUserId} />
                )}

                {currentTab === 'settings' && (
                    <SettingsPage userId={selectedUserId} />
                )}
            </Box>
        </Box>
    )
}

export default App
