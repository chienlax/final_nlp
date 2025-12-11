/**
 * Denoising Page (formerly Processing Page)
 * 
 * Batch noise processing queue management using DeepFilterNet.
 * Lists chunks flagged for denoising and allows triggering batch denoise.
 */

import { useState } from 'react'
import {
    Box,
    Typography,
    Button,
    Alert,
    Chip,
    CircularProgress,
    LinearProgress
} from '@mui/material'
import { PlayArrow, Refresh, VolumeOff, CheckCircle, Pending, Error } from '@mui/icons-material'
import { DataGrid, GridColDef, GridRenderCellParams } from '@mui/x-data-grid'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '../api/client'
import '../styles/workbench.css'

interface DenoiseQueueItem {
    id: number
    chunk_id: number
    video_title: string
    chunk_index: number
    denoise_status: 'flagged' | 'queued' | 'processed' | 'failed'
    flagged_at: string
}

interface ProcessingPageProps {
    userId: number
}

export function ProcessingPage({ userId }: ProcessingPageProps) {
    const queryClient = useQueryClient()
    const [isRunning, setIsRunning] = useState(false)

    // Configure API header
    api.defaults.headers.common['X-User-ID'] = userId.toString()

    // Fetch denoise queue
    const { data: queue = [], isLoading, error, refetch } = useQuery<DenoiseQueueItem[]>({
        queryKey: ['denoise', 'queue'],
        queryFn: () => api.get('/chunks/denoise-queue').then(res => res.data).catch(() => []),
    })

    // Run batch denoise mutation
    const denoiseMutation = useMutation({
        mutationFn: () => api.post('/denoise/run'),
        onMutate: () => setIsRunning(true),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['denoise'] })
            setIsRunning(false)
        },
        onError: () => setIsRunning(false),
    })

    // Get status chip props
    const getStatusChip = (status: string) => {
        switch (status) {
            case 'flagged':
                return { icon: <VolumeOff />, color: 'warning' as const, label: 'Flagged' }
            case 'queued':
                return { icon: <Pending />, color: 'info' as const, label: 'Queued' }
            case 'processed':
                return { icon: <CheckCircle />, color: 'success' as const, label: 'Processed' }
            case 'failed':
                return { icon: <Error />, color: 'error' as const, label: 'Failed' }
            default:
                return { icon: <Pending />, color: 'default' as const, label: status }
        }
    }

    // DataGrid columns
    const columns: GridColDef[] = [
        {
            field: 'video_title',
            headerName: 'Video',
            flex: 2,
            minWidth: 200,
        },
        {
            field: 'chunk_index',
            headerName: 'Chunk',
            width: 100,
            renderCell: (params: GridRenderCellParams) => `#${params.value}`
        },
        {
            field: 'denoise_status',
            headerName: 'Status',
            width: 140,
            renderCell: (params: GridRenderCellParams) => {
                const chipProps = getStatusChip(params.value)
                return (
                    <Chip
                        icon={chipProps.icon}
                        label={chipProps.label}
                        color={chipProps.color}
                        size="small"
                    />
                )
            }
        },
        {
            field: 'flagged_at',
            headerName: 'Flagged',
            width: 180,
            renderCell: (params: GridRenderCellParams) => {
                if (!params.value) return '-'
                return new Date(params.value).toLocaleString()
            }
        },
    ]

    // Count by status
    const flaggedCount = queue.filter(q => q.denoise_status === 'flagged').length
    const queuedCount = queue.filter(q => q.denoise_status === 'queued').length
    const processedCount = queue.filter(q => q.denoise_status === 'processed').length

    if (error) {
        return (
            <Box className="processing-container">
                <Alert severity="error">Failed to load denoise queue.</Alert>
            </Box>
        )
    }

    return (
        <Box className="processing-container">
            {/* Header */}
            <Box className="processing-header">
                <Box>
                    <Typography variant="h5">🔊 Noise Processing Queue</Typography>
                    <Typography variant="body2" color="text.secondary">
                        Manage audio chunks flagged for denoising
                    </Typography>
                </Box>

                <Box className="processing-actions">
                    <Button
                        variant="outlined"
                        startIcon={<Refresh />}
                        onClick={() => refetch()}
                        disabled={isLoading}
                    >
                        Refresh
                    </Button>
                    <Button
                        variant="contained"
                        color="warning"
                        startIcon={isRunning ? <CircularProgress size={20} /> : <PlayArrow />}
                        onClick={() => denoiseMutation.mutate()}
                        disabled={isRunning || flaggedCount === 0}
                    >
                        {isRunning ? 'Processing...' : `Run Batch Denoise (${flaggedCount})`}
                    </Button>
                </Box>
            </Box>

            {/* Stats */}
            <Box className="processing-stats">
                <Box className="stat-card warning">
                    <VolumeOff />
                    <Typography variant="h4">{flaggedCount}</Typography>
                    <Typography>Flagged</Typography>
                </Box>
                <Box className="stat-card info">
                    <Pending />
                    <Typography variant="h4">{queuedCount}</Typography>
                    <Typography>In Queue</Typography>
                </Box>
                <Box className="stat-card success">
                    <CheckCircle />
                    <Typography variant="h4">{processedCount}</Typography>
                    <Typography>Processed</Typography>
                </Box>
            </Box>

            {/* Progress if running */}
            {isRunning && (
                <Box sx={{ mb: 2 }}>
                    <Typography variant="body2" sx={{ mb: 1 }}>Processing audio files...</Typography>
                    <LinearProgress color="warning" />
                </Box>
            )}

            {/* Queue Table */}
            <Box className="processing-queue">
                {isLoading ? (
                    <Box sx={{ display: 'flex', justifyContent: 'center', p: 4 }}>
                        <CircularProgress />
                    </Box>
                ) : queue.length === 0 ? (
                    <Alert severity="info">
                        No chunks flagged for denoising. Flag noisy audio during annotation to add them here.
                    </Alert>
                ) : (
                    <DataGrid
                        rows={queue}
                        columns={columns}
                        pageSizeOptions={[10, 25, 50]}
                        initialState={{
                            pagination: { paginationModel: { pageSize: 10 } }
                        }}
                        disableRowSelectionOnClick
                        sx={{
                            border: 'none',
                            '& .MuiDataGrid-columnHeaders': {
                                bgcolor: 'rgba(0,0,0,0.3)',
                            },
                            '& .MuiDataGrid-cell': {
                                borderColor: 'rgba(255,255,255,0.05)',
                            },
                        }}
                    />
                )}
            </Box>
        </Box>
    )
}
