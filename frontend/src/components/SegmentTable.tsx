import { useState, useCallback } from 'react'
import {
    Box,
    IconButton,
    Checkbox,
    TextField,
    Tooltip,
} from '@mui/material'
import {
    PlayArrow as PlayIcon,
    Save as SaveIcon,
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
    onPlaySegment?: (startTime: number) => void
}

// Format time as M:SS.mmm
function formatTime(seconds: number): string {
    const mins = Math.floor(seconds / 60)
    const secs = Math.floor(seconds % 60)
    const ms = Math.floor((seconds % 1) * 1000)
    return `${mins}:${secs.toString().padStart(2, '0')}.${ms.toString().padStart(3, '0')}`
}

export function SegmentTable({ segments, chunkId, onPlaySegment }: SegmentTableProps) {
    const queryClient = useQueryClient()
    const [editedRows, setEditedRows] = useState<Map<number, Partial<Segment>>>(new Map())

    // Update segment mutation
    const updateMutation = useMutation({
        mutationFn: ({ id, ...data }: { id: number } & Partial<Segment>) =>
            api.put(`/segments/${id}`, data),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['segments', chunkId] })
        },
    })

    // Toggle verification mutation
    const verifyMutation = useMutation({
        mutationFn: (id: number) => api.post(`/segments/${id}/verify`),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['segments', chunkId] })
        },
    })

    // Handle cell edit
    const handleCellEdit = useCallback((id: number, field: string, value: string | number) => {
        setEditedRows(prev => {
            const newMap = new Map(prev)
            const existing = newMap.get(id) || {}
            newMap.set(id, { ...existing, [field]: value })
            return newMap
        })
    }, [])

    // Save edited row
    const handleSave = useCallback((id: number) => {
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

    const columns: GridColDef[] = [
        {
            field: 'play',
            headerName: '',
            width: 50,
            sortable: false,
            renderCell: (params: GridRenderCellParams<Segment>) => (
                <IconButton
                    size="small"
                    onClick={() => onPlaySegment?.(params.row.start_time_relative)}
                >
                    <PlayIcon fontSize="small" />
                </IconButton>
            ),
        },
        {
            field: 'start_time_relative',
            headerName: 'Start',
            width: 90,
            renderCell: (params: GridRenderCellParams<Segment>) => (
                <TextField
                    size="small"
                    variant="standard"
                    value={formatTime(getValue(params.row, 'start_time_relative') as number)}
                    onChange={(e) => {
                        // Parse time string back to seconds
                        const match = e.target.value.match(/^(\d+):(\d{2})\.(\d{3})$/)
                        if (match) {
                            const seconds = parseInt(match[1]) * 60 + parseInt(match[2]) + parseInt(match[3]) / 1000
                            handleCellEdit(params.row.id, 'start_time_relative', seconds)
                        }
                    }}
                    sx={{ width: 80 }}
                />
            ),
        },
        {
            field: 'end_time_relative',
            headerName: 'End',
            width: 90,
            renderCell: (params: GridRenderCellParams<Segment>) => (
                <TextField
                    size="small"
                    variant="standard"
                    value={formatTime(getValue(params.row, 'end_time_relative') as number)}
                    onChange={(e) => {
                        const match = e.target.value.match(/^(\d+):(\d{2})\.(\d{3})$/)
                        if (match) {
                            const seconds = parseInt(match[1]) * 60 + parseInt(match[2]) + parseInt(match[3]) / 1000
                            handleCellEdit(params.row.id, 'end_time_relative', seconds)
                        }
                    }}
                    sx={{ width: 80 }}
                />
            ),
        },
        {
            field: 'transcript',
            headerName: 'Transcript',
            flex: 1,
            minWidth: 200,
            renderCell: (params: GridRenderCellParams<Segment>) => (
                <TextField
                    size="small"
                    variant="standard"
                    fullWidth
                    multiline
                    maxRows={3}
                    value={getValue(params.row, 'transcript') as string}
                    onChange={(e) => handleCellEdit(params.row.id, 'transcript', e.target.value)}
                />
            ),
        },
        {
            field: 'translation',
            headerName: 'Translation',
            flex: 1,
            minWidth: 200,
            renderCell: (params: GridRenderCellParams<Segment>) => (
                <TextField
                    size="small"
                    variant="standard"
                    fullWidth
                    multiline
                    maxRows={3}
                    value={getValue(params.row, 'translation') as string}
                    onChange={(e) => handleCellEdit(params.row.id, 'translation', e.target.value)}
                />
            ),
        },
        {
            field: 'is_verified',
            headerName: '✓',
            width: 50,
            renderCell: (params: GridRenderCellParams<Segment>) => (
                <Checkbox
                    checked={params.row.is_verified}
                    onChange={() => verifyMutation.mutate(params.row.id)}
                    size="small"
                />
            ),
        },
        {
            field: 'save',
            headerName: '',
            width: 50,
            sortable: false,
            renderCell: (params: GridRenderCellParams<Segment>) => (
                <Tooltip title="Save changes">
                    <span>
                        <IconButton
                            size="small"
                            onClick={() => handleSave(params.row.id)}
                            disabled={!editedRows.has(params.row.id)}
                            color={editedRows.has(params.row.id) ? 'primary' : 'default'}
                        >
                            <SaveIcon fontSize="small" />
                        </IconButton>
                    </span>
                </Tooltip>
            ),
        },
    ]

    return (
        <Box sx={{ height: 400, width: '100%' }}>
            <DataGrid
                rows={segments}
                columns={columns}
                pageSizeOptions={[10, 25, 50]}
                initialState={{
                    pagination: { paginationModel: { pageSize: 10 } },
                }}
                disableRowSelectionOnClick
                getRowHeight={() => 'auto'}
                sx={{
                    '& .MuiDataGrid-cell': {
                        py: 1,
                    },
                }}
            />
        </Box>
    )
}
