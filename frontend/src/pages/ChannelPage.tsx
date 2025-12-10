/**
 * Channel Page - Video List with Accordion Chunk Expansion
 * 
 * Shows all videos within a selected channel in list view.
 * Click video row to expand/collapse chunk list.
 * Click chunk to navigate to WorkbenchPage.
 */

import { useState } from 'react'
import {
    Box,
    Typography,
    IconButton,
    Chip,
    Button,
    Alert,
    Skeleton,
    Collapse,
    Table,
    TableBody,
    TableCell,
    TableContainer,
    TableHead,
    TableRow,
    Paper,
} from '@mui/material'
import {
    ArrowBack,
    ExpandMore,
    ExpandLess,
    Lock,
    CheckCircle,
    HourglassEmpty,
    VolumeOff,
    PlayArrow,
    AccessTime,
} from '@mui/icons-material'
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

interface ChunkInfo {
    id: number
    video_id: number
    chunk_index: number
    audio_path: string
    status: string
    denoise_status: string
    locked_by_user_id: number | null
    locked_by_username: string | null
    lock_expires_at: string | null
    segment_count: number
}

interface ChannelPageProps {
    userId: number
    channel: Channel
    onVideoSelect: (videoId: number, chunkId?: number) => void
    onBack: () => void
}

export function ChannelPage({ userId, channel, onVideoSelect, onBack }: ChannelPageProps) {
    const [expandedVideoId, setExpandedVideoId] = useState<number | null>(null)

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

    // Fetch chunks for expanded video
    const { data: chunks = [], isLoading: loadingChunks } = useQuery<ChunkInfo[]>({
        queryKey: ['video', 'chunks', expandedVideoId],
        queryFn: () => api.get(`/videos/${expandedVideoId}/chunks`).then(res => res.data),
        enabled: !!expandedVideoId,
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

    // Toggle video expansion
    const toggleExpand = (videoId: number) => {
        setExpandedVideoId(prev => prev === videoId ? null : videoId)
    }

    // Get chunk status display
    const getChunkStatusChip = (chunk: ChunkInfo) => {
        if (chunk.locked_by_username) {
            return (
                <Chip
                    icon={<Lock fontSize="small" />}
                    label={`Locked by ${chunk.locked_by_username}`}
                    size="small"
                    color="warning"
                    variant="outlined"
                />
            )
        }

        switch (chunk.status) {
            case 'approved':
                return <Chip icon={<CheckCircle fontSize="small" />} label="Approved" size="small" color="success" />
            case 'review_ready':
            case 'in_review':
                return <Chip icon={<PlayArrow fontSize="small" />} label="Ready" size="small" color="info" />
            case 'pending':
                return <Chip icon={<HourglassEmpty fontSize="small" />} label="Processing" size="small" color="default" />
            default:
                return <Chip label={chunk.status} size="small" />
        }
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

            {/* Video List */}
            <Box className="video-section" sx={{ mt: 2 }}>
                {isLoading ? (
                    <Box>
                        {[1, 2, 3].map(i => (
                            <Skeleton key={i} variant="rounded" height={60} sx={{ mb: 1 }} />
                        ))}
                    </Box>
                ) : videos.length === 0 ? (
                    <Alert severity="info">
                        No videos in this channel yet. Use the ingestion tool to add videos.
                    </Alert>
                ) : (
                    <TableContainer component={Paper} sx={{ bgcolor: 'rgba(255,255,255,0.02)' }}>
                        <Table>
                            <TableHead>
                                <TableRow>
                                    <TableCell width={40}></TableCell>
                                    <TableCell>Video Title</TableCell>
                                    <TableCell width={100}>Duration</TableCell>
                                    <TableCell width={200}>Progress</TableCell>
                                    <TableCell width={120}>Actions</TableCell>
                                </TableRow>
                            </TableHead>
                            <TableBody>
                                {videos.map(video => {
                                    const stats = getVideoStats(video.id)
                                    const isExpanded = expandedVideoId === video.id
                                    const readyCount = (stats?.pending_chunks || 0)
                                    const approvedCount = stats?.approved_chunks || 0
                                    const totalCount = stats?.total_chunks || 0

                                    return (
                                        <>
                                            {/* Video Row */}
                                            <TableRow
                                                key={video.id}
                                                hover
                                                sx={{
                                                    cursor: 'pointer',
                                                    bgcolor: isExpanded ? 'rgba(144, 202, 249, 0.08)' : 'inherit',
                                                    '&:hover': { bgcolor: 'rgba(255,255,255,0.05)' }
                                                }}
                                                onClick={() => toggleExpand(video.id)}
                                            >
                                                <TableCell>
                                                    <IconButton size="small">
                                                        {isExpanded ? <ExpandLess /> : <ExpandMore />}
                                                    </IconButton>
                                                </TableCell>
                                                <TableCell>
                                                    <Typography
                                                        variant="body1"
                                                        sx={{
                                                            fontWeight: 500,
                                                            maxWidth: 400,
                                                            overflow: 'hidden',
                                                            textOverflow: 'ellipsis',
                                                            whiteSpace: 'nowrap'
                                                        }}
                                                        title={video.title}
                                                    >
                                                        {video.title}
                                                    </Typography>
                                                </TableCell>
                                                <TableCell>
                                                    <Chip
                                                        icon={<AccessTime sx={{ fontSize: 14 }} />}
                                                        label={formatDuration(video.duration_seconds)}
                                                        size="small"
                                                        variant="outlined"
                                                    />
                                                </TableCell>
                                                <TableCell>
                                                    <Typography variant="body2" color="text.secondary">
                                                        {approvedCount}/{totalCount} approved
                                                        {readyCount > 0 && ` • ${readyCount} ready`}
                                                    </Typography>
                                                </TableCell>
                                                <TableCell>
                                                    <Button
                                                        size="small"
                                                        variant="text"
                                                        onClick={(e) => {
                                                            e.stopPropagation()
                                                            toggleExpand(video.id)
                                                        }}
                                                    >
                                                        {isExpanded ? 'Collapse' : 'Show Chunks'}
                                                    </Button>
                                                </TableCell>
                                            </TableRow>

                                            {/* Chunk List (Expanded) */}
                                            <TableRow key={`${video.id}-chunks`}>
                                                <TableCell colSpan={5} sx={{ p: 0, border: 0 }}>
                                                    <Collapse in={isExpanded} timeout="auto" unmountOnExit>
                                                        <Box sx={{
                                                            bgcolor: 'rgba(0,0,0,0.2)',
                                                            p: 2,
                                                            borderLeft: '3px solid #90caf9'
                                                        }}>
                                                            {loadingChunks ? (
                                                                <Skeleton variant="rounded" height={100} />
                                                            ) : chunks.length === 0 ? (
                                                                <Typography color="text.secondary">
                                                                    No chunks found for this video.
                                                                </Typography>
                                                            ) : (
                                                                <Table size="small">
                                                                    <TableHead>
                                                                        <TableRow>
                                                                            <TableCell>Chunk</TableCell>
                                                                            <TableCell>Status</TableCell>
                                                                            <TableCell>Segments</TableCell>
                                                                            <TableCell>Denoise</TableCell>
                                                                            <TableCell>Action</TableCell>
                                                                        </TableRow>
                                                                    </TableHead>
                                                                    <TableBody>
                                                                        {chunks.map(chunk => (
                                                                            <TableRow
                                                                                key={chunk.id}
                                                                                hover
                                                                                sx={{ '&:hover': { bgcolor: 'rgba(255,255,255,0.03)' } }}
                                                                            >
                                                                                <TableCell>
                                                                                    <Typography fontWeight={500}>
                                                                                        #{chunk.chunk_index + 1}
                                                                                    </Typography>
                                                                                </TableCell>
                                                                                <TableCell>
                                                                                    {getChunkStatusChip(chunk)}
                                                                                </TableCell>
                                                                                <TableCell>
                                                                                    {chunk.segment_count} segments
                                                                                </TableCell>
                                                                                <TableCell>
                                                                                    {chunk.denoise_status === 'flagged' && (
                                                                                        <Chip
                                                                                            icon={<VolumeOff fontSize="small" />}
                                                                                            label="Flagged"
                                                                                            size="small"
                                                                                            color="warning"
                                                                                        />
                                                                                    )}
                                                                                </TableCell>
                                                                                <TableCell>
                                                                                    <Button
                                                                                        size="small"
                                                                                        variant="contained"
                                                                                        disabled={!!chunk.locked_by_username || chunk.status === 'pending'}
                                                                                        onClick={() => onVideoSelect(video.id, chunk.id)}
                                                                                    >
                                                                                        {chunk.status === 'approved' ? 'View' : 'Review'}
                                                                                    </Button>
                                                                                </TableCell>
                                                                            </TableRow>
                                                                        ))}
                                                                    </TableBody>
                                                                </Table>
                                                            )}
                                                        </Box>
                                                    </Collapse>
                                                </TableCell>
                                            </TableRow>
                                        </>
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
