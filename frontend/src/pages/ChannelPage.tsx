/**
 * Channel Page (gemini_ui_2)
 * 
 * Shows all videos within a selected channel.
 * Click a video to navigate to Annotation tab.
 */

import { Box, Typography, Card, CardContent, Grid, Chip, Button, IconButton, Skeleton, Alert, LinearProgress } from '@mui/material'
import { ArrowBack, PlayArrow, VideoLibrary, AccessTime, CheckCircle, Edit } from '@mui/icons-material'
import { useQuery } from '@tanstack/react-query'
import axios from 'axios'
import '../styles/workbench.css'

const api = axios.create({ baseURL: '/api' })

interface Channel {
    id: number
    name: string
    url: string
}

interface Video {
    id: number
    title: string
    channel_id: number
    duration_seconds: number
    original_url: string
    status: string
    created_at: string
}

interface VideoStats {
    video_id: number
    total_chunks: number
    pending_chunks: number
    approved_chunks: number
    total_segments: number
    verified_segments: number
}

interface ChannelPageProps {
    userId: number
    channel: Channel
    onVideoSelect: (videoId: number, chunkId?: number) => void
    onBack: () => void
}

export function ChannelPage({ userId, channel, onVideoSelect, onBack }: ChannelPageProps) {
    // Configure API header
    api.defaults.headers.common['X-User-ID'] = userId.toString()

    // Fetch videos for this channel
    const { data: videos = [], isLoading, error } = useQuery<Video[]>({
        queryKey: ['videos', channel.id],
        queryFn: () => api.get(`/channels/${channel.id}/videos`).then(res => res.data),
    })

    // Fetch video stats
    const { data: videoStats = [] } = useQuery<VideoStats[]>({
        queryKey: ['videos', 'stats', channel.id],
        queryFn: () => api.get(`/channels/${channel.id}/videos/stats`).then(res => res.data).catch(() => []),
    })

    // Get stats for a video
    const getVideoStats = (videoId: number): VideoStats | undefined => {
        return videoStats.find(s => s.video_id === videoId)
    }

    // Format duration
    const formatDuration = (seconds: number): string => {
        const hours = Math.floor(seconds / 3600)
        const mins = Math.floor((seconds % 3600) / 60)
        if (hours > 0) return `${hours}h ${mins}m`
        return `${mins}m`
    }

    // Calculate progress percentage
    const getProgress = (stats?: VideoStats): number => {
        if (!stats || stats.total_chunks === 0) return 0
        return Math.round((stats.approved_chunks / stats.total_chunks) * 100)
    }

    if (error) {
        return (
            <Box className="channel-page">
                <Alert severity="error">Failed to load videos for this channel.</Alert>
            </Box>
        )
    }

    return (
        <Box className="channel-page">
            {/* Header */}
            <Box className="channel-page-header">
                <IconButton onClick={onBack} sx={{ color: 'white', mr: 2 }}>
                    <ArrowBack />
                </IconButton>
                <Box>
                    <Typography variant="h5">{channel.name}</Typography>
                    <Typography variant="body2" color="text.secondary">
                        {videos.length} videos
                    </Typography>
                </Box>
            </Box>

            {/* Video Grid */}
            <Box className="video-section">
                {isLoading ? (
                    <Grid container spacing={3}>
                        {[1, 2, 3, 4].map(i => (
                            <Grid key={i} item xs={12} sm={6} md={4} lg={3}>
                                <Skeleton variant="rounded" height={220} />
                            </Grid>
                        ))}
                    </Grid>
                ) : videos.length === 0 ? (
                    <Alert severity="info">
                        No videos in this channel yet. Use the ingestion tool to add videos.
                    </Alert>
                ) : (
                    <Grid container spacing={3}>
                        {videos.map(video => {
                            const stats = getVideoStats(video.id)
                            const progress = getProgress(stats)
                            const hasPending = (stats?.pending_chunks || 0) > 0

                            return (
                                <Grid key={video.id} item xs={12} sm={6} md={4} lg={3}>
                                    <Card className="video-card">
                                        <CardContent>
                                            {/* Video thumbnail placeholder */}
                                            <Box className="video-thumbnail">
                                                <VideoLibrary sx={{ fontSize: 48, color: 'rgba(255,255,255,0.3)' }} />
                                            </Box>

                                            {/* Video title */}
                                            <Typography variant="subtitle1" className="video-title" noWrap title={video.title}>
                                                {video.title}
                                            </Typography>

                                            {/* Duration and date */}
                                            <Box className="video-meta">
                                                <Chip
                                                    icon={<AccessTime sx={{ fontSize: 14 }} />}
                                                    label={formatDuration(video.duration_seconds)}
                                                    size="small"
                                                    variant="outlined"
                                                />
                                            </Box>

                                            {/* Stats */}
                                            <Box className="video-stats">
                                                <Box className="stat-row">
                                                    <Typography variant="body2">
                                                        Chunks: {stats?.approved_chunks || 0}/{stats?.total_chunks || 0}
                                                    </Typography>
                                                </Box>
                                                <LinearProgress
                                                    variant="determinate"
                                                    value={progress}
                                                    sx={{
                                                        height: 6,
                                                        borderRadius: 3,
                                                        bgcolor: 'rgba(255,255,255,0.1)',
                                                        '& .MuiLinearProgress-bar': {
                                                            bgcolor: progress === 100 ? '#4caf50' : '#90caf9'
                                                        }
                                                    }}
                                                />
                                            </Box>

                                            {/* Actions */}
                                            <Box className="video-actions">
                                                {hasPending ? (
                                                    <Button
                                                        variant="contained"
                                                        size="small"
                                                        startIcon={<Edit />}
                                                        onClick={() => onVideoSelect(video.id)}
                                                        fullWidth
                                                    >
                                                        Start Review ({stats?.pending_chunks})
                                                    </Button>
                                                ) : progress === 100 ? (
                                                    <Chip
                                                        icon={<CheckCircle />}
                                                        label="Complete"
                                                        color="success"
                                                        size="small"
                                                    />
                                                ) : (
                                                    <Button
                                                        variant="outlined"
                                                        size="small"
                                                        startIcon={<PlayArrow />}
                                                        onClick={() => onVideoSelect(video.id)}
                                                        fullWidth
                                                    >
                                                        View
                                                    </Button>
                                                )}
                                            </Box>
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
