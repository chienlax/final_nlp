/**
 * Enhanced Segment Table Component
 * 
 * Features:
 * - 2-second debounced auto-save
 * - Active row highlighting
 * - Keyboard navigation (Ctrl+Enter to save and next)
 * - Verify checkbox per row
 * - Unsaved changes indicator
 * - Bidirectional sync with waveform
 */

import { useState, useCallback, useEffect, useRef, useMemo } from 'react'
import {
    Box,
    IconButton,
    Checkbox,
    TextField,
    Tooltip,
    Typography,
} from '@mui/material'
import {
    PlayArrow as PlayIcon,
    CheckCircle,
    Circle,
} from '@mui/icons-material'
import { DataGrid, GridColDef, GridRenderCellParams } from '@mui/x-data-grid'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import axios from 'axios'

const api = axios.create({ baseURL: '/api' })

interface Segment {
    id: number
    chunk_id: number
    start_time_relative: number
    end_time_relative: number
    transcript: string
    translation: string
    is_verified: boolean
}

interface SegmentTableProps {
    segments: Segment[]
    chunkId: number
    activeSegmentId?: number | null
    onPlaySegment?: (startTime: number, endTime: number, segmentId: number) => void
    onSegmentChange?: () => void
    onSegmentSaved?: () => void
    onActiveChange?: (segmentId: number | null) => void
}

// Format time as M:SS.mmm
function formatTime(seconds: number): string {
    const mins = Math.floor(seconds / 60)
    const secs = Math.floor(seconds % 60)
    const ms = Math.floor((seconds % 1) * 1000)
    return `${mins}:${secs.toString().padStart(2, '0')}.${ms.toString().padStart(3, '0')}`
}

// Parse time string M:SS.mmm to seconds
function parseTime(timeStr: string): number | null {
    const match = timeStr.match(/^(\d+):(\d{2})\.(\d{3})$/)
    if (match) {
        return parseInt(match[1]) * 60 + parseInt(match[2]) + parseInt(match[3]) / 1000
    }
    return null
}

// Debounce hook
function useDebounce<T>(value: T, delay: number): T {
    const [debouncedValue, setDebouncedValue] = useState(value)

    useEffect(() => {
        const timer = setTimeout(() => setDebouncedValue(value), delay)
        return () => clearTimeout(timer)
    }, [value, delay])

    return debouncedValue
}

export function SegmentTable({
    segments,
    chunkId,
    activeSegmentId,
    onPlaySegment,
    onSegmentChange,
    onSegmentSaved,
    onActiveChange,
}: SegmentTableProps) {
    const queryClient = useQueryClient()
    const [editedRows, setEditedRows] = useState<Map<number, Partial<Segment>>>(new Map())
    const [focusedRowId, setFocusedRowId] = useState<number | null>(null)
    const tableRef = useRef<HTMLDivElement>(null)

    // Debounced edited rows for auto-save
    const debouncedEditedRows = useDebounce(editedRows, 2000)

    // Update segment mutation
    const updateMutation = useMutation({
        mutationFn: ({ id, ...data }: { id: number } & Partial<Segment>) =>
            api.put(`/segments/${id}`, data),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['segments', chunkId] })
            onSegmentSaved?.()
        },
    })

    // Toggle verification mutation
    const verifyMutation = useMutation({
        mutationFn: (id: number) => api.post(`/segments/${id}/verify`),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['segments', chunkId] })
        },
    })

    // Auto-save on debounced changes
    useEffect(() => {
        if (debouncedEditedRows.size > 0) {
            debouncedEditedRows.forEach((changes, id) => {
                if (Object.keys(changes).length > 0) {
                    updateMutation.mutate({ id, ...changes })
                }
            })
            setEditedRows(new Map())
        }
    }, [debouncedEditedRows])

    // Handle cell edit
    const handleCellEdit = useCallback((id: number, field: string, value: string | number) => {
        setEditedRows(prev => {
            const newMap = new Map(prev)
            const existing = newMap.get(id) || {}
            newMap.set(id, { ...existing, [field]: value })
            return newMap
        })
        onSegmentChange?.()
    }, [onSegmentChange])

    // Save specific row immediately
    const handleSaveRow = useCallback((id: number) => {
        const edited = editedRows.get(id)
        if (edited) {
            updateMutation.mutate({ id, ...edited })
            setEditedRows(prev => {
                const newMap = new Map(prev)
                newMap.delete(id)
                return newMap
            })
        }
    }, [editedRows, updateMutation])

    // Get current value (edited or original)
    const getValue = useCallback((row: Segment, field: keyof Segment) => {
        const edited = editedRows.get(row.id)
        if (edited && field in edited) {
            return edited[field]
        }
        return row[field]
    }, [editedRows])

    // Check if row has unsaved changes
    const hasChanges = useCallback((id: number) => {
        return editedRows.has(id) && Object.keys(editedRows.get(id) || {}).length > 0
    }, [editedRows])

    // Move to next row (Ctrl+Enter)
    const moveToNextRow = useCallback((currentId: number) => {
        const currentIndex = segments.findIndex(s => s.id === currentId)
        if (currentIndex >= 0 && currentIndex < segments.length - 1) {
            const nextSegment = segments[currentIndex + 1]
            setFocusedRowId(nextSegment.id)
            onActiveChange?.(nextSegment.id)
        }
    }, [segments, onActiveChange])

    // Keyboard handler for table
    useEffect(() => {
        const handleKeyDown = (e: KeyboardEvent) => {
            if (e.ctrlKey && e.key === 'Enter' && focusedRowId) {
                e.preventDefault()
                handleSaveRow(focusedRowId)
                moveToNextRow(focusedRowId)
            }
        }

        tableRef.current?.addEventListener('keydown', handleKeyDown)
        return () => tableRef.current?.removeEventListener('keydown', handleKeyDown)
    }, [focusedRowId, handleSaveRow, moveToNextRow])

    // Scroll active row into view
    useEffect(() => {
        if (activeSegmentId && tableRef.current) {
            const row = tableRef.current.querySelector(`[data-id="${activeSegmentId}"]`)
            row?.scrollIntoView({ behavior: 'smooth', block: 'center' })
        }
    }, [activeSegmentId])

    const columns: GridColDef[] = useMemo(() => [
        {
            field: 'is_verified',
            headerName: '✓',
            width: 50,
            renderCell: (params: GridRenderCellParams<Segment>) => (
                <Tooltip title={params.row.is_verified ? 'Verified' : 'Click to verify'}>
                    <Checkbox
                        checked={params.row.is_verified}
                        onChange={() => verifyMutation.mutate(params.row.id)}
                        size="small"
                        icon={<Circle fontSize="small" sx={{ color: 'rgba(255,255,255,0.3)' }} />}
                        checkedIcon={<CheckCircle fontSize="small" sx={{ color: '#4caf50' }} />}
                    />
                </Tooltip>
            ),
        },
        {
            field: 'play',
            headerName: '',
            width: 50,
            sortable: false,
            renderCell: (params: GridRenderCellParams<Segment>) => (
                <IconButton
                    size="small"
                    onClick={() => onPlaySegment?.(
                        params.row.start_time_relative,
                        params.row.end_time_relative,
                        params.row.id
                    )}
                    sx={{ color: activeSegmentId === params.row.id ? '#ffc107' : 'inherit' }}
                >
                    <PlayIcon fontSize="small" />
                </IconButton>
            ),
        },
        {
            field: 'start_time_relative',
            headerName: 'Start',
            width: 100,
            renderCell: (params: GridRenderCellParams<Segment>) => (
                <TextField
                    size="small"
                    variant="standard"
                    value={formatTime(getValue(params.row, 'start_time_relative') as number)}
                    onChange={(e) => {
                        const seconds = parseTime(e.target.value)
                        if (seconds !== null) {
                            handleCellEdit(params.row.id, 'start_time_relative', seconds)
                        }
                    }}
                    onFocus={() => setFocusedRowId(params.row.id)}
                    sx={{
                        width: 90,
                        '& input': {
                            fontFamily: 'JetBrains Mono, monospace',
                            fontSize: 13,
                        }
                    }}
                />
            ),
        },
        {
            field: 'end_time_relative',
            headerName: 'End',
            width: 100,
            renderCell: (params: GridRenderCellParams<Segment>) => (
                <TextField
                    size="small"
                    variant="standard"
                    value={formatTime(getValue(params.row, 'end_time_relative') as number)}
                    onChange={(e) => {
                        const seconds = parseTime(e.target.value)
                        if (seconds !== null) {
                            handleCellEdit(params.row.id, 'end_time_relative', seconds)
                        }
                    }}
                    onFocus={() => setFocusedRowId(params.row.id)}
                    sx={{
                        width: 90,
                        '& input': {
                            fontFamily: 'JetBrains Mono, monospace',
                            fontSize: 13,
                        }
                    }}
                />
            ),
        },
        {
            field: 'transcript',
            headerName: 'Transcript (VI/EN)',
            flex: 1,
            minWidth: 250,
            renderCell: (params: GridRenderCellParams<Segment>) => (
                <TextField
                    size="small"
                    variant="standard"
                    fullWidth
                    multiline
                    maxRows={3}
                    value={getValue(params.row, 'transcript') as string}
                    onChange={(e) => handleCellEdit(params.row.id, 'transcript', e.target.value)}
                    onFocus={() => setFocusedRowId(params.row.id)}
                    placeholder="Original speech..."
                    sx={{
                        '& input, & textarea': { fontSize: 14 },
                    }}
                />
            ),
        },
        {
            field: 'translation',
            headerName: 'Translation (EN)',
            flex: 1,
            minWidth: 250,
            renderCell: (params: GridRenderCellParams<Segment>) => (
                <TextField
                    size="small"
                    variant="standard"
                    fullWidth
                    multiline
                    maxRows={3}
                    value={getValue(params.row, 'translation') as string}
                    onChange={(e) => handleCellEdit(params.row.id, 'translation', e.target.value)}
                    onFocus={() => setFocusedRowId(params.row.id)}
                    placeholder="English translation..."
                    sx={{
                        '& input, & textarea': { fontSize: 14 },
                    }}
                />
            ),
        },
        {
            field: 'status',
            headerName: '',
            width: 30,
            sortable: false,
            renderCell: (params: GridRenderCellParams<Segment>) => (
                hasChanges(params.row.id) ? (
                    <Tooltip title="Unsaved changes (auto-saves in 2s)">
                        <Box
                            sx={{
                                width: 8,
                                height: 8,
                                borderRadius: '50%',
                                bgcolor: '#2196f3',
                                animation: 'pulse 2s infinite',
                            }}
                        />
                    </Tooltip>
                ) : null
            ),
        },
    ], [activeSegmentId, editedRows, getValue, handleCellEdit, hasChanges, onPlaySegment, verifyMutation])

    return (
        <Box ref={tableRef} sx={{ height: '100%', width: '100%' }}>
            <DataGrid
                rows={segments}
                columns={columns}
                pageSizeOptions={[25, 50, 100]}
                initialState={{
                    pagination: { paginationModel: { pageSize: 25 } },
                }}
                disableRowSelectionOnClick
                getRowHeight={() => 'auto'}
                getRowClassName={(params) => {
                    const classes = []
                    if (params.row.id === activeSegmentId) classes.push('active-row')
                    if (hasChanges(params.row.id)) classes.push('unsaved')
                    return classes.join(' ')
                }}
                onRowClick={(params) => onActiveChange?.(params.row.id)}
                sx={{
                    border: 'none',
                    '& .MuiDataGrid-cell': {
                        py: 1.5,
                        borderBottom: '1px solid rgba(255,255,255,0.05)',
                    },
                    '& .MuiDataGrid-columnHeaders': {
                        bgcolor: 'rgba(0,0,0,0.3)',
                        borderBottom: '1px solid rgba(255,255,255,0.1)',
                    },
                    '& .MuiDataGrid-row': {
                        transition: 'background 0.2s',
                    },
                    '& .MuiDataGrid-row:hover': {
                        bgcolor: 'rgba(255,255,255,0.05)',
                    },
                    '& .MuiDataGrid-row.active-row': {
                        bgcolor: 'rgba(255, 193, 7, 0.1)',
                        borderLeft: '3px solid #ffc107',
                    },
                    '& .MuiDataGrid-row.unsaved': {
                        bgcolor: 'rgba(33, 150, 243, 0.08)',
                    },
                }}
            />

            {/* Keyboard hint */}
            {focusedRowId && (
                <Typography
                    variant="caption"
                    sx={{
                        display: 'block',
                        textAlign: 'right',
                        mt: 1,
                        color: 'rgba(255,255,255,0.4)'
                    }}
                >
                    Ctrl+Enter to save and move to next row
                </Typography>
            )}
        </Box>
    )
}
