/**
 * Dashboard Page (gemini_ui_1)
 * 
 * Overview of all channels with statistics and system stats.
 * Click a channel row to navigate to Channel tab.
 */

import {
    Box,
    Typography,
    Chip,
    Skeleton,
    Alert,
    Table,
    TableBody,
    TableCell,
    TableContainer,
    TableHead,
    TableRow,
    Paper,
    Button,
} from '@mui/material'
import { Folder, VideoLibrary, Pending, CheckCircle, AccessTime, ChevronRight } from '@mui/icons-material'
import { useQuery } from '@tanstack/react-query'
import axios from 'axios'
import '../styles/workbench.css'

const api = axios.create({ baseURL: '/api' })

interface Channel {
    id: number
    name: string
    url: string
}

interface ChannelStats {
    channel_id: number
    total_videos: number
    total_chunks: number
    pending_chunks: number
    approved_chunks: number
}

interface SystemStats {
    total_channels: number
    total_videos: number
    total_chunks: number
    total_segments: number
    approved_segments: number
    total_hours: number
}

interface DashboardPageProps {
    userId: number
    onChannelSelect: (channel: Channel) => void
}

export function DashboardPage({ userId, onChannelSelect }: DashboardPageProps) {
    // Configure API header
    api.defaults.headers.common['X-User-ID'] = userId.toString()

    // Fetch channels
    const { data: channels = [], isLoading: loadingChannels, error: channelError } = useQuery<Channel[]>({
        queryKey: ['channels'],
        queryFn: () => api.get('/channels').then(res => res.data),
    })

    // Fetch channel stats
    const { data: channelStats = [] } = useQuery<ChannelStats[]>({
        queryKey: ['channels', 'stats'],
        queryFn: () => api.get('/channels/stats').then(res => res.data).catch(() => []),
    })

    // Fetch system stats
    const { data: systemStats } = useQuery<SystemStats>({
        queryKey: ['system', 'stats'],
        queryFn: () => api.get('/stats').then(res => res.data).catch(() => null),
    })

    // Get stats for a channel
    const getChannelStats = (channelId: number): ChannelStats | undefined => {
        return channelStats.find(s => s.channel_id === channelId)
    }

    if (channelError) {
        return (
            <Box className="dashboard-container">
                <Alert severity="error">Failed to load channels. Is the backend running?</Alert>
            </Box>
        )
    }

    return (
        <Box className="dashboard-container">
            {/* System Stats Panel */}
            <Box className="stats-panel">
                <Typography variant="h5" className="panel-title">
                    📊 System Overview
                </Typography>
                <Box className="stats-grid">
                    <Box className="stat-card">
                        <Folder sx={{ fontSize: 40, color: '#90caf9' }} />
                        <Typography variant="h4">{systemStats?.total_channels || channels.length}</Typography>
                        <Typography color="text.secondary">Channels</Typography>
                    </Box>
                    <Box className="stat-card">
                        <VideoLibrary sx={{ fontSize: 40, color: '#80deea' }} />
                        <Typography variant="h4">{systemStats?.total_videos || 0}</Typography>
                        <Typography color="text.secondary">Videos</Typography>
                    </Box>
                    <Box className="stat-card">
                        <AccessTime sx={{ fontSize: 40, color: '#a5d6a7' }} />
                        <Typography variant="h4">{systemStats?.total_hours?.toFixed(1) || '0.0'}</Typography>
                        <Typography color="text.secondary">Hours</Typography>
                    </Box>
                    <Box className="stat-card">
                        <Pending sx={{ fontSize: 40, color: '#ffcc80' }} />
                        <Typography variant="h4">{systemStats?.total_chunks || 0}</Typography>
                        <Typography color="text.secondary">Total Chunks</Typography>
                    </Box>
                    <Box className="stat-card">
                        <CheckCircle sx={{ fontSize: 40, color: '#81c784' }} />
                        <Typography variant="h4">{systemStats?.approved_segments || 0}</Typography>
                        <Typography color="text.secondary">Verified Segments</Typography>
                    </Box>
                </Box>
            </Box>

            {/* Channel List */}
            <Box className="channel-section">
                <Typography variant="h5" className="section-title">
                    📁 Channels
                </Typography>

                {loadingChannels ? (
                    <Box>
                        {[1, 2, 3].map(i => (
                            <Skeleton key={i} variant="rounded" height={56} sx={{ mb: 1 }} />
                        ))}
                    </Box>
                ) : channels.length === 0 ? (
                    <Alert severity="info">
                        No channels yet. Use the ingestion tool to add YouTube channels.
                    </Alert>
                ) : (
                    <TableContainer component={Paper} sx={{ bgcolor: 'rgba(255,255,255,0.02)' }}>
                        <Table>
                            <TableHead>
                                <TableRow>
                                    <TableCell>Channel Name</TableCell>
                                    <TableCell width={100}>Videos</TableCell>
                                    <TableCell width={120}>Pending</TableCell>
                                    <TableCell width={120}>Approved</TableCell>
                                    <TableCell width={140}>Status</TableCell>
                                    <TableCell width={100}>Action</TableCell>
                                </TableRow>
                            </TableHead>
                            <TableBody>
                                {channels.map(channel => {
                                    const stats = getChannelStats(channel.id)
                                    const hasPending = (stats?.pending_chunks || 0) > 0

                                    return (
                                        <TableRow
                                            key={channel.id}
                                            hover
                                            sx={{
                                                cursor: 'pointer',
                                                '&:hover': { bgcolor: 'rgba(255,255,255,0.05)' }
                                            }}
                                            onClick={() => onChannelSelect(channel)}
                                        >
                                            <TableCell>
                                                <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                                                    <Folder sx={{ color: '#90caf9' }} />
                                                    <Typography fontWeight={500}>
                                                        {channel.name}
                                                    </Typography>
                                                </Box>
                                            </TableCell>
                                            <TableCell>
                                                <Chip
                                                    icon={<VideoLibrary sx={{ fontSize: 16 }} />}
                                                    label={stats?.total_videos || 0}
                                                    size="small"
                                                    variant="outlined"
                                                />
                                            </TableCell>
                                            <TableCell>
                                                <Chip
                                                    icon={<Pending sx={{ fontSize: 16 }} />}
                                                    label={stats?.pending_chunks || 0}
                                                    size="small"
                                                    color={hasPending ? 'warning' : 'default'}
                                                    variant={hasPending ? 'filled' : 'outlined'}
                                                />
                                            </TableCell>
                                            <TableCell>
                                                <Chip
                                                    icon={<CheckCircle sx={{ fontSize: 16 }} />}
                                                    label={stats?.approved_chunks || 0}
                                                    size="small"
                                                    color={(stats?.approved_chunks || 0) > 0 ? 'success' : 'default'}
                                                    variant="outlined"
                                                />
                                            </TableCell>
                                            <TableCell>
                                                {hasPending ? (
                                                    <Chip
                                                        label="Needs review"
                                                        size="small"
                                                        color="warning"
                                                    />
                                                ) : (stats?.approved_chunks || 0) > 0 ? (
                                                    <Chip
                                                        label="Up to date"
                                                        size="small"
                                                        color="success"
                                                        variant="outlined"
                                                    />
                                                ) : (
                                                    <Chip
                                                        label="Empty"
                                                        size="small"
                                                        variant="outlined"
                                                    />
                                                )}
                                            </TableCell>
                                            <TableCell>
                                                <Button
                                                    size="small"
                                                    endIcon={<ChevronRight />}
                                                    onClick={(e) => {
                                                        e.stopPropagation()
                                                        onChannelSelect(channel)
                                                    }}
                                                >
                                                    View
                                                </Button>
                                            </TableCell>
                                        </TableRow>
                                    )
                                })}
                            </TableBody>
                        </Table>
                    </TableContainer>
                )}
            </Box>
        </Box>
    )
}
