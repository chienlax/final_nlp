/**
 * Annotation Workbench Page
 * 
 * 3-Zone Layout:
 * - Zone A: Control Header (breadcrumbs, denoise toggle, lock status, save/finish)
 * - Zone B: Waveform Visualizer (30% viewport)
 * - Zone C: Editor Table (70% viewport, scrollable)
 */

import { useState, useEffect, useRef, useCallback, useMemo } from 'react'
import {
    Box,
    Button,
    ButtonGroup,
    IconButton,
    Chip,
    Typography,
    Breadcrumbs,
    Link,
    Tooltip,
    CircularProgress,
    Alert,
    Snackbar,
} from '@mui/material'
import {
    PlayArrow,
    Pause,
    VolumeUp,
    VolumeOff,
    CheckCircle,
    Save,
    Home,
    NavigateNext,
    ZoomIn,
    ZoomOut,
    Lock,
    SkipNext,
    Speed,
} from '@mui/icons-material'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import axios from 'axios'
import { WaveformViewer, WaveformViewerRef } from '../components/WaveformViewer'
import { SegmentTable } from '../components/SegmentTable'
import '../styles/workbench.css'

// Types
interface Chunk {
    id: number
    video_id: number
    chunk_index: number
    audio_path: string
    status: string
    denoise_status: string
    locked_by_user_id: number | null
    lock_expires_at: string | null
    video_title: string
    total_chunks: number
}

interface Segment {
    id: number
    chunk_id: number
    start_time_relative: number
    end_time_relative: number
    transcript: string
    translation: string
    is_verified: boolean
}

// Channel interface removed - not used in this component

const api = axios.create({ baseURL: '/api' })

interface WorkbenchPageProps {
    userId: number
    username: string
    preselectedVideoId?: number | null
    preselectedChunkId?: number | null
}

export function WorkbenchPage({ userId, username, preselectedVideoId, preselectedChunkId }: WorkbenchPageProps) {
    const queryClient = useQueryClient()

    // State
    const [currentChunk, setCurrentChunk] = useState<Chunk | null>(null)
    const [isPlaying, setIsPlaying] = useState(false)
    const [currentTime, setCurrentTime] = useState(0)
    const [duration, setDuration] = useState(0)
    const [zoom, setZoom] = useState(1)
    const [playbackRate, setPlaybackRate] = useState(1)  // Persisted across chunks
    const [activeSegmentId, setActiveSegmentId] = useState<number | null>(null)
    const [hasUnsavedChanges, setHasUnsavedChanges] = useState(false)
    const [snackbar, setSnackbar] = useState<{ open: boolean; message: string; severity: 'success' | 'error' | 'info' }>({
        open: false,
        message: '',
        severity: 'info'
    })

    // Refs
    const waveformRef = useRef<WaveformViewerRef>(null)
    const saveAllRef = useRef<(() => void) | null>(null)  // Save function from SegmentTable

    // Configure axios with user ID
    useEffect(() => {
        api.defaults.headers.common['X-User-ID'] = userId.toString()
    }, [userId])

    // Fetch specific chunk if preselectedChunkId is provided
    const { data: preselectedChunk, isLoading: loadingPreselected } = useQuery<Chunk | null>({
        queryKey: ['chunk', preselectedChunkId],
        queryFn: () => api.get(`/chunks/${preselectedChunkId}`).then(res => res.data),
        enabled: !!preselectedChunkId && !currentChunk,
    })

    // Fetch next available chunk - only if no preselectedChunkId
    const { data: nextChunk, isLoading: loadingNext, refetch: refetchNext } = useQuery<Chunk | null>({
        queryKey: ['chunks', 'next', userId, preselectedVideoId],
        queryFn: () => {
            const params = new URLSearchParams()
            if (preselectedVideoId) {
                params.append('video_id', preselectedVideoId.toString())
            }
            const url = params.toString() ? `/chunks/next?${params}` : '/chunks/next'
            return api.get(url).then(res => res.data)
        },
        enabled: !currentChunk && !preselectedChunkId,
    })

    // Use preselected chunk or next chunk
    const effectiveNextChunk = preselectedChunkId ? preselectedChunk : nextChunk
    const loadingChunk = preselectedChunkId ? loadingPreselected : loadingNext

    // Fetch segments for current chunk
    const { data: segments = [], isLoading: loadingSegments, refetch: refetchSegments } = useQuery<Segment[]>({
        queryKey: ['segments', currentChunk?.id],
        queryFn: () => api.get(`/chunks/${currentChunk?.id}/segments`).then(res => res.data),
        enabled: !!currentChunk,
    })

    // Lock chunk mutation
    const lockMutation = useMutation({
        mutationFn: (chunkId: number) => api.post(`/chunks/${chunkId}/lock`),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['chunks'] })
            showSnackbar('Chunk locked successfully', 'success')
        },
        onError: (error: any) => {
            showSnackbar(error.response?.data?.detail || 'Failed to lock chunk', 'error')
        }
    })

    // Approve chunk mutation
    const approveMutation = useMutation({
        mutationFn: (chunkId: number) => api.post(`/chunks/${chunkId}/approve`),
        onSuccess: () => {
            setCurrentChunk(null)
            queryClient.invalidateQueries({ queryKey: ['chunks'] })
            refetchNext()
            showSnackbar('Chunk approved! Loading next...', 'success')
        },
    })

    // Flag for denoise mutation - TOGGLES based on API response
    const denoiseMutation = useMutation({
        mutationFn: (chunkId: number) => api.post(`/chunks/${chunkId}/flag-noise`),
        onSuccess: (response) => {
            if (currentChunk) {
                // Use actual status from API response
                setCurrentChunk({ ...currentChunk, denoise_status: response.data.denoise_status })
            }
            showSnackbar(response.data.message, 'info')
        },
    })

    // Global bulk verify ALL segments in current chunk
    const bulkVerifyAllMutation = useMutation({
        mutationFn: (segmentIds: number[]) => api.post('/segments/bulk-verify', { segment_ids: segmentIds }),
        onSuccess: (response) => {
            queryClient.invalidateQueries({ queryKey: ['segments', currentChunk?.id] })
            showSnackbar(response.data.message, 'success')
        },
    })

    // Global bulk reject ALL segments in current chunk  
    const bulkRejectAllMutation = useMutation({
        mutationFn: (segmentIds: number[]) => api.post('/segments/bulk-reject', { segment_ids: segmentIds }),
        onSuccess: (response) => {
            queryClient.invalidateQueries({ queryKey: ['segments', currentChunk?.id] })
            showSnackbar(response.data.message, 'info')
        },
    })

    // Computed values
    const verifiedCount = useMemo(() =>
        segments.filter(s => s.is_verified).length,
        [segments]
    )

    const allVerified = useMemo(() =>
        segments.length > 0 && verifiedCount === segments.length,
        [segments.length, verifiedCount]
    )

    const isDenoiseActive = currentChunk?.denoise_status === 'flagged'

    // Helpers
    const showSnackbar = (message: string, severity: 'success' | 'error' | 'info') => {
        setSnackbar({ open: true, message, severity })
    }

    const formatTime = (seconds: number): string => {
        const mins = Math.floor(seconds / 60)
        const secs = Math.floor(seconds % 60)
        const ms = Math.floor((seconds % 1) * 1000)
        return `${mins}:${secs.toString().padStart(2, '0')}.${ms.toString().padStart(3, '0')}`
    }

    // Start working on a chunk
    const startChunk = async (chunk: Chunk) => {
        try {
            await lockMutation.mutateAsync(chunk.id)
            setCurrentChunk(chunk)
        } catch (err) {
            console.error('Failed to lock chunk:', err)
        }
    }

    // Keyboard shortcuts
    useEffect(() => {
        const handleKeyDown = (e: KeyboardEvent) => {
            // Ignore if typing in input
            if (['INPUT', 'TEXTAREA'].includes((e.target as HTMLElement).tagName)) {
                // Only handle Ctrl+Enter in inputs
                if (e.ctrlKey && e.key === 'Enter') {
                    e.preventDefault()
                    // Move to next row - handled by SegmentTable
                }
                return
            }

            if (e.ctrlKey) {
                switch (e.code) {
                    case 'Space':
                        e.preventDefault()
                        if (isPlaying) {
                            waveformRef.current?.pause()
                        } else {
                            waveformRef.current?.play()
                        }
                        break
                    case 'KeyD':
                        e.preventDefault()
                        if (currentChunk) {
                            denoiseMutation.mutate(currentChunk.id)
                        }
                        break
                    case 'ArrowRight':
                        e.preventDefault()
                        waveformRef.current?.skip(5)
                        break
                    case 'ArrowLeft':
                        e.preventDefault()
                        waveformRef.current?.skip(-5)
                        break
                    case 'KeyS':
                        e.preventDefault()
                        // Trigger save - handled by SegmentTable
                        break
                }
            }
        }

        window.addEventListener('keydown', handleKeyDown)
        return () => window.removeEventListener('keydown', handleKeyDown)
    }, [isPlaying, currentChunk])

    // Play segment callback
    const playSegment = useCallback((startTime: number, endTime: number, segmentId: number) => {
        setActiveSegmentId(segmentId)
        waveformRef.current?.playRegion(startTime, endTime)
    }, [])

    // Region update callback (from waveform drag)
    const handleRegionUpdate = useCallback((_regionId: string, _start: number, _end: number) => {
        setHasUnsavedChanges(true)
        // TODO: Implement segment timestamp update via API
    }, [])

    // Handle segment update from table
    const handleSegmentChange = useCallback(() => {
        setHasUnsavedChanges(true)
    }, [])

    const handleSegmentSaved = useCallback(() => {
        setHasUnsavedChanges(false)
        refetchSegments()
    }, [refetchSegments])

    // ==========================================================================
    // RENDER
    // ==========================================================================

    // Loading state
    if (loadingChunk && !currentChunk) {
        return (
            <Box className="workbench-container" sx={{ justifyContent: 'center', alignItems: 'center' }}>
                <CircularProgress size={60} />
                <Typography sx={{ mt: 2 }}>Loading chunk...</Typography>
            </Box>
        )
    }

    // No work available
    if (!currentChunk && !effectiveNextChunk) {
        return (
            <Box className="workbench-container" sx={{ justifyContent: 'center', alignItems: 'center' }}>
                <Alert severity="success" sx={{ maxWidth: 400 }}>
                    <Typography variant="h6">🎉 All caught up!</Typography>
                    <Typography>No pending chunks require review.</Typography>
                </Alert>
            </Box>
        )
    }

    // Start review prompt
    if (!currentChunk && effectiveNextChunk) {
        return (
            <Box className="workbench-container" sx={{ justifyContent: 'center', alignItems: 'center' }}>
                <Box sx={{
                    p: 4,
                    background: 'var(--glass-bg)',
                    borderRadius: 3,
                    textAlign: 'center',
                    maxWidth: 500
                }}>
                    <Typography variant="h5" gutterBottom>
                        Ready to Review
                    </Typography>
                    <Typography variant="h6" color="primary" gutterBottom>
                        {effectiveNextChunk.video_title}
                    </Typography>
                    <Typography color="text.secondary" gutterBottom>
                        Chunk {effectiveNextChunk.chunk_index + 1} of {effectiveNextChunk.total_chunks}
                    </Typography>
                    <Button
                        variant="contained"
                        size="large"
                        startIcon={<PlayArrow />}
                        onClick={() => startChunk(effectiveNextChunk)}
                        disabled={lockMutation.isPending}
                        sx={{ mt: 2 }}
                    >
                        {lockMutation.isPending ? 'Acquiring Lock...' : 'Start Review'}
                    </Button>
                </Box>
            </Box>
        )
    }

    // Safety guard: Wait for segments to load before rendering workbench
    if (currentChunk && loadingSegments) {
        return (
            <Box className="workbench-container" sx={{ justifyContent: 'center', alignItems: 'center' }}>
                <CircularProgress size={60} />
                <Typography sx={{ mt: 2 }}>Loading segments...</Typography>
            </Box>
        )
    }

    // Safety guard: Ensure audio path exists
    if (!currentChunk?.audio_path) {
        return (
            <Box className="workbench-container" sx={{ justifyContent: 'center', alignItems: 'center' }}>
                <Alert severity="error">
                    <Typography>Error: No audio path available for this chunk.</Typography>
                </Alert>
            </Box>
        )
    }

    // Main workbench view
    return (
        <Box className="workbench-container">
            {/* ================================================================
                ZONE A: Control Header
            ================================================================ */}
            <Box className="zone-header">
                {/* Left: Breadcrumbs */}
                <Box className="zone-header-left">
                    <Breadcrumbs
                        separator={<NavigateNext fontSize="small" />}
                        sx={{ color: 'rgba(255,255,255,0.7)' }}
                    >
                        <Link
                            href="#"
                            underline="hover"
                            color="inherit"
                            sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}
                        >
                            <Home fontSize="small" />
                            Dashboard
                        </Link>
                        <Link href="#" underline="hover" color="inherit">
                            {currentChunk?.video_title?.split(' ')[0] || 'Channel'}
                        </Link>
                        <Typography color="text.primary" sx={{ fontWeight: 600 }}>
                            Chunk #{(currentChunk?.chunk_index || 0) + 1}
                        </Typography>
                    </Breadcrumbs>
                </Box>

                {/* Center: Denoise toggle + Lock status */}
                <Box className="zone-header-center">
                    <Tooltip title="Ctrl+D to toggle">
                        <Button
                            variant={isDenoiseActive ? 'contained' : 'outlined'}
                            size="small"
                            startIcon={isDenoiseActive ? <VolumeOff /> : <VolumeUp />}
                            onClick={() => currentChunk && denoiseMutation.mutate(currentChunk.id)}
                            sx={{
                                bgcolor: isDenoiseActive ? 'var(--denoise-active)' : 'transparent',
                                borderColor: isDenoiseActive ? 'var(--denoise-active)' : 'rgba(255,255,255,0.3)',
                                '&:hover': {
                                    bgcolor: isDenoiseActive ? '#f57c00' : 'rgba(255,255,255,0.1)',
                                }
                            }}
                        >
                            {isDenoiseActive ? 'Flagged Noisy' : 'Flag as Noisy'}
                        </Button>
                    </Tooltip>

                    <Chip
                        icon={<Lock fontSize="small" />}
                        label={`Locked by ${username}`}
                        size="small"
                        sx={{
                            bgcolor: 'rgba(76, 175, 80, 0.2)',
                            color: 'var(--lock-owned)',
                            border: '1px solid var(--lock-owned)',
                        }}
                    />

                    {hasUnsavedChanges && (
                        <Box className="unsaved-indicator">
                            <Save fontSize="small" />
                            Unsaved changes
                        </Box>
                    )}
                </Box>

                {/* Right: Global actions + Save + Finish buttons */}
                <Box className="zone-header-right">
                    {/* Global Verify All / Reject All */}
                    <ButtonGroup size="small" sx={{ mr: 1 }}>
                        <Button
                            variant="outlined"
                            color="success"
                            onClick={() => bulkVerifyAllMutation.mutate(segments.map(s => s.id))}
                            disabled={bulkVerifyAllMutation.isPending || segments.length === 0}
                        >
                            Verify All
                        </Button>
                        <Button
                            variant="outlined"
                            color="error"
                            onClick={() => bulkRejectAllMutation.mutate(segments.map(s => s.id))}
                            disabled={bulkRejectAllMutation.isPending || segments.length === 0}
                        >
                            Reject All
                        </Button>
                    </ButtonGroup>

                    <Button
                        variant="outlined"
                        startIcon={<Save />}
                        disabled={!hasUnsavedChanges}
                        onClick={() => {
                            // Trigger manual save via SegmentTable's saveAllRef
                            if (saveAllRef.current) {
                                saveAllRef.current()
                            }
                            setHasUnsavedChanges(false)
                            showSnackbar('Changes saved', 'success')
                        }}
                    >
                        Save Changes
                    </Button>

                    <Tooltip title={!allVerified ? `${verifiedCount}/${segments.length} segments verified` : 'All segments verified!'}>
                        <span>
                            <Button
                                variant="contained"
                                color="success"
                                startIcon={<CheckCircle />}
                                onClick={() => currentChunk && approveMutation.mutate(currentChunk.id)}
                                disabled={!allVerified || approveMutation.isPending}
                            >
                                Mark as Finished
                            </Button>
                        </span>
                    </Tooltip>
                </Box>
            </Box>

            {/* ================================================================
                ZONE B: Waveform Visualizer
            ================================================================ */}
            <Box className="zone-waveform">
                <Box className="waveform-container">
                    <WaveformViewer
                        ref={waveformRef}
                        audioUrl={`/api/static/${currentChunk?.audio_path}`}
                        segments={segments}
                        activeSegmentId={activeSegmentId}
                        zoom={zoom}
                        onPlayPause={setIsPlaying}
                        onTimeUpdate={setCurrentTime}
                        onDurationChange={setDuration}
                        onRegionUpdate={handleRegionUpdate}
                        onRegionClick={(id) => setActiveSegmentId(Number(id))}
                    />
                </Box>

                <Box className="waveform-controls">
                    <IconButton
                        onClick={() => isPlaying ? waveformRef.current?.pause() : waveformRef.current?.play()}
                        sx={{ bgcolor: 'rgba(255,255,255,0.1)' }}
                    >
                        {isPlaying ? <Pause /> : <PlayArrow />}
                    </IconButton>

                    <Box className="time-display">
                        {formatTime(currentTime)} / {formatTime(duration)}
                    </Box>

                    <Tooltip title="Skip 5s forward (Ctrl+→)">
                        <IconButton onClick={() => waveformRef.current?.skip(5)}>
                            <SkipNext />
                        </IconButton>
                    </Tooltip>

                    {/* Playback Speed Control */}
                    <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5, mx: 1 }}>
                        <Speed fontSize="small" sx={{ color: 'rgba(255,255,255,0.5)' }} />
                        {[0.75, 1, 1.25, 1.5, 2].map((rate) => (
                            <Button
                                key={rate}
                                size="small"
                                variant={playbackRate === rate ? 'contained' : 'text'}
                                onClick={() => {
                                    setPlaybackRate(rate)
                                    waveformRef.current?.setPlaybackRate(rate)
                                }}
                                sx={{
                                    minWidth: 40,
                                    px: 1,
                                    fontSize: 12,
                                    bgcolor: playbackRate === rate ? 'primary.main' : 'transparent',
                                    color: playbackRate === rate ? 'white' : 'rgba(255,255,255,0.6)',
                                    '&:hover': {
                                        bgcolor: playbackRate === rate ? 'primary.dark' : 'rgba(255,255,255,0.1)',
                                    }
                                }}
                            >
                                {rate}x
                            </Button>
                        ))}
                    </Box>

                    <Box className="zoom-controls">
                        <IconButton onClick={() => setZoom(z => Math.max(1, z - 0.5))} disabled={zoom <= 1}>
                            <ZoomOut fontSize="small" />
                        </IconButton>
                        <Typography variant="caption" sx={{ mx: 1 }}>{zoom.toFixed(1)}x</Typography>
                        <IconButton onClick={() => setZoom(z => Math.min(10, z + 0.5))}>
                            <ZoomIn fontSize="small" />
                        </IconButton>
                    </Box>
                </Box>
            </Box>

            {/* ================================================================
                ZONE C: Editor Table
            ================================================================ */}
            <Box className="zone-table">
                <Box className="table-header">
                    <Typography variant="h6">
                        Segments ({segments.length})
                    </Typography>
                    <Typography
                        variant="body2"
                        className={allVerified ? 'verified-count complete' : 'verified-count'}
                    >
                        {verifiedCount} / {segments.length} verified
                        {allVerified && ' ✓'}
                    </Typography>
                </Box>

                <Box className="table-container segment-table">
                    {loadingSegments ? (
                        <Box sx={{ display: 'flex', justifyContent: 'center', p: 4 }}>
                            <CircularProgress />
                        </Box>
                    ) : (
                        <SegmentTable
                            segments={segments}
                            chunkId={currentChunk?.id || 0}
                            activeSegmentId={activeSegmentId}
                            onPlaySegment={playSegment}
                            onSegmentChange={handleSegmentChange}
                            onSegmentSaved={handleSegmentSaved}
                            onActiveChange={setActiveSegmentId}
                            saveAllRef={saveAllRef}
                        />
                    )}
                </Box>
            </Box>

            {/* Snackbar notifications */}
            <Snackbar
                open={snackbar.open}
                autoHideDuration={3000}
                onClose={() => setSnackbar(s => ({ ...s, open: false }))}
                anchorOrigin={{ vertical: 'bottom', horizontal: 'center' }}
            >
                <Alert severity={snackbar.severity} onClose={() => setSnackbar(s => ({ ...s, open: false }))}>
                    {snackbar.message}
                </Alert>
            </Snackbar>
        </Box>
    )
}
