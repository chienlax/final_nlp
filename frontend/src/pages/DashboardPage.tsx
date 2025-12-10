/**
 * Dashboard Page (gemini_ui_1)
 * 
 * Overview of all channels with statistics and system stats.
 * Click a channel card to navigate to Channel tab.
 */

import { Box, Typography, Card, CardContent, Grid, Chip, Skeleton, Alert } from '@mui/material'
import { Folder, VideoLibrary, Pending, CheckCircle, AccessTime } from '@mui/icons-material'
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

            {/* Channel Grid */}
            <Box className="channel-section">
                <Typography variant="h5" className="section-title">
                    📁 Channels
                </Typography>

                {loadingChannels ? (
                    <Grid container spacing={3}>
                        {[1, 2, 3].map(i => (
                            <Grid key={i} item xs={12} sm={6} md={4}>
                                <Skeleton variant="rounded" height={180} />
                            </Grid>
                        ))}
                    </Grid>
                ) : channels.length === 0 ? (
                    <Alert severity="info">
                        No channels yet. Use the ingestion tool to add YouTube channels.
                    </Alert>
                ) : (
                    <Grid container spacing={3}>
                        {channels.map(channel => {
                            const stats = getChannelStats(channel.id)
                            return (
                                <Grid key={channel.id} item xs={12} sm={6} md={4} lg={3}>
                                    <Card
                                        className="channel-card"
                                        onClick={() => onChannelSelect(channel)}
                                    >
                                        <CardContent>
                                            <Box className="channel-card-header">
                                                <Folder sx={{ fontSize: 32, color: '#90caf9' }} />
                                                <Typography variant="h6" noWrap>
                                                    {channel.name}
                                                </Typography>
                                            </Box>

                                            <Box className="channel-card-stats">
                                                <Box className="stat-row">
                                                    <VideoLibrary fontSize="small" />
                                                    <Typography>{stats?.total_videos || 0} videos</Typography>
                                                </Box>
                                                <Box className="stat-row">
                                                    <Pending fontSize="small" />
                                                    <Typography>{stats?.pending_chunks || 0} pending</Typography>
                                                </Box>
                                                <Box className="stat-row">
                                                    <CheckCircle fontSize="small" />
                                                    <Typography>{stats?.approved_chunks || 0} approved</Typography>
                                                </Box>
                                            </Box>

                                            {stats && stats.pending_chunks > 0 && (
                                                <Chip
                                                    label={`${stats.pending_chunks} needs review`}
                                                    size="small"
                                                    color="warning"
                                                    sx={{ mt: 1 }}
                                                />
                                            )}
                                        </CardContent>
                                    </Card>
                                </Grid>
                            )
                        })}
                    </Grid>
                )}
            </Box>
        </Box>
    )
}
