import { useState, useEffect, useRef, useCallback } from 'react'
import {
    Box,
    Paper,
    Typography,
    Button,
    IconButton,
    Chip,
    Stack,
    Switch,
    FormControlLabel,
    Alert,
    CircularProgress,
} from '@mui/material'
import {
    PlayArrow,
    Pause,
    NavigateNext,
    Save,
    CheckCircle,
    VolumeUp,
} from '@mui/icons-material'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import axios from 'axios'
import { WaveformViewer } from '../components/WaveformViewer'
import { SegmentTable } from '../components/SegmentTable'

// Types
interface Chunk {
    id: number
    video_id: number
    chunk_index: number
    audio_path: string
    status: string
    denoise_status: string
    locked_by_user_id: number | null
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

const api = axios.create({ baseURL: '/api' })

interface WorkbenchPageProps {
    userId: number
}

export function WorkbenchPage({ userId }: WorkbenchPageProps) {
    const queryClient = useQueryClient()
    const [currentChunk, setCurrentChunk] = useState<Chunk | null>(null)
    const [isPlaying, setIsPlaying] = useState(false)
    const [denoiseEnabled, setDenoiseEnabled] = useState(false)
    const waveformRef = useRef<{ play: () => void; pause: () => void; seekTo: (time: number) => void } | null>(null)

    // Configure axios with user ID
    useEffect(() => {
        api.defaults.headers.common['X-User-ID'] = userId.toString()
    }, [userId])

    // Fetch next available chunk
    const { data: nextChunk, isLoading: loadingNext, refetch: refetchNext } = useQuery<Chunk | null>({
        queryKey: ['chunks', 'next', userId],
        queryFn: () => api.get('/chunks/next').then(res => res.data),
        enabled: !currentChunk,
    })

    // Fetch segments for current chunk
    const { data: segments, isLoading: loadingSegments } = useQuery<Segment[]>({
        queryKey: ['segments', currentChunk?.id],
        queryFn: () => api.get(`/chunks/${currentChunk?.id}/segments`).then(res => res.data),
        enabled: !!currentChunk,
    })

    // Lock chunk mutation
    const lockMutation = useMutation({
        mutationFn: (chunkId: number) => api.post(`/chunks/${chunkId}/lock`),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['chunks'] })
        },
    })

    // Approve chunk mutation
    const approveMutation = useMutation({
        mutationFn: (chunkId: number) => api.post(`/chunks/${chunkId}/approve`),
        onSuccess: () => {
            setCurrentChunk(null)
            queryClient.invalidateQueries({ queryKey: ['chunks'] })
            refetchNext()
        },
    })

    // Flag for denoise mutation
    const denoiseMutation = useMutation({
        mutationFn: (chunkId: number) => api.post(`/chunks/${chunkId}/flag-noise`),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['chunks'] })
        },
    })

    // Start working on a chunk
    const startChunk = async (chunk: Chunk) => {
        try {
            await lockMutation.mutateAsync(chunk.id)
            setCurrentChunk(chunk)
        } catch (err) {
            console.error('Failed to lock chunk:', err)
        }
    }

    // Handle keyboard shortcuts
    useEffect(() => {
        const handleKeyDown = (e: KeyboardEvent) => {
            if (e.ctrlKey && e.code === 'Space') {
                e.preventDefault()
                if (isPlaying) {
                    waveformRef.current?.pause()
                } else {
                    waveformRef.current?.play()
                }
                setIsPlaying(!isPlaying)
            }
        }

        window.addEventListener('keydown', handleKeyDown)
        return () => window.removeEventListener('keydown', handleKeyDown)
    }, [isPlaying])

    // Play segment callback
    const playSegment = useCallback((startTime: number) => {
        waveformRef.current?.seekTo(startTime)
        waveformRef.current?.play()
        setIsPlaying(true)
    }, [])

    return (
        <Box>
            {/* No work available */}
            {!currentChunk && !loadingNext && !nextChunk && (
                <Alert severity="success" sx={{ mb: 2 }}>
                    🎉 No pending work! All chunks are reviewed.
                </Alert>
            )}

            {/* Loading */}
            {loadingNext && (
                <Box display="flex" justifyContent="center" py={4}>
                    <CircularProgress />
                </Box>
            )}

            {/* Next available chunk */}
            {!currentChunk && nextChunk && (
                <Paper sx={{ p: 3, mb: 3 }}>
                    <Typography variant="h6" gutterBottom>
                        Next Available: {nextChunk.video_title}
                    </Typography>
                    <Typography color="text.secondary" gutterBottom>
                        Chunk {nextChunk.chunk_index + 1} of {nextChunk.total_chunks}
                    </Typography>
                    <Button
                        variant="contained"
                        startIcon={<PlayArrow />}
                        onClick={() => startChunk(nextChunk)}
                        disabled={lockMutation.isPending}
                    >
                        {lockMutation.isPending ? 'Locking...' : 'Start Review'}
                    </Button>
                </Paper>
            )}

            {/* Current chunk workbench */}
            {currentChunk && (
                <>
                    {/* Header */}
                    <Paper sx={{ p: 2, mb: 2 }}>
                        <Stack direction="row" alignItems="center" spacing={2}>
                            <Box sx={{ flexGrow: 1 }}>
                                <Typography variant="h6">
                                    {currentChunk.video_title}
                                </Typography>
                                <Typography variant="body2" color="text.secondary">
                                    Chunk {currentChunk.chunk_index + 1} / {currentChunk.total_chunks}
                                </Typography>
                            </Box>

                            <FormControlLabel
                                control={
                                    <Switch
                                        checked={denoiseEnabled}
                                        onChange={(e) => {
                                            setDenoiseEnabled(e.target.checked)
                                            if (e.target.checked) {
                                                denoiseMutation.mutate(currentChunk.id)
                                            }
                                        }}
                                    />
                                }
                                label="Flag for Denoise"
                            />

                            <Chip
                                label={currentChunk.status}
                                color={currentChunk.status === 'approved' ? 'success' : 'default'}
                            />

                            <Button
                                variant="contained"
                                color="success"
                                startIcon={<CheckCircle />}
                                onClick={() => approveMutation.mutate(currentChunk.id)}
                                disabled={approveMutation.isPending}
                            >
                                Approve & Next
                            </Button>
                        </Stack>
                    </Paper>

                    {/* Waveform */}
                    <Paper sx={{ p: 2, mb: 2 }}>
                        <WaveformViewer
                            ref={waveformRef}
                            audioUrl={`/api/static/${currentChunk.audio_path}`}
                            onPlayPause={(playing) => setIsPlaying(playing)}
                            segments={segments || []}
                        />

                        <Stack direction="row" spacing={1} sx={{ mt: 2 }}>
                            <Button
                                variant="outlined"
                                startIcon={isPlaying ? <Pause /> : <PlayArrow />}
                                onClick={() => {
                                    if (isPlaying) {
                                        waveformRef.current?.pause()
                                    } else {
                                        waveformRef.current?.play()
                                    }
                                    setIsPlaying(!isPlaying)
                                }}
                            >
                                {isPlaying ? 'Pause' : 'Play'}
                            </Button>
                            <Typography variant="caption" color="text.secondary" sx={{ alignSelf: 'center' }}>
                                Ctrl+Space to play/pause
                            </Typography>
                        </Stack>
                    </Paper>

                    {/* Segments table */}
                    <Paper sx={{ p: 2 }}>
                        <Typography variant="h6" gutterBottom>
                            Segments ({segments?.length || 0})
                        </Typography>

                        {loadingSegments ? (
                            <CircularProgress />
                        ) : (
                            <SegmentTable
                                segments={segments || []}
                                chunkId={currentChunk.id}
                                onPlaySegment={playSegment}
                            />
                        )}
                    </Paper>
                </>
            )}
        </Box>
    )
}
