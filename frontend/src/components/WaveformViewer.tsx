/**
 * Enhanced Waveform Viewer Component
 * 
 * Features:
 * - Large zoomable waveform
 * - Colored regions (green=verified, blue=unverified, yellow=active)
 * - Timeline with MM:SS labels
 * - Region drag to update timestamps
 * - Click region to play loop
 * - Minimap for navigation
 */

import { useEffect, useRef, forwardRef, useImperativeHandle } from 'react'
import WaveSurfer from 'wavesurfer.js'
import RegionsPlugin, { Region } from 'wavesurfer.js/dist/plugins/regions.esm.js'
import TimelinePlugin from 'wavesurfer.js/dist/plugins/timeline.esm.js'
import MinimapPlugin from 'wavesurfer.js/dist/plugins/minimap.esm.js'
import { Box } from '@mui/material'

interface Segment {
    id: number
    start_time_relative: number
    end_time_relative: number
    transcript: string
    is_verified: boolean
}

interface WaveformViewerProps {
    audioUrl: string
    segments?: Segment[]
    activeSegmentId?: number | null
    zoom?: number
    onPlayPause?: (isPlaying: boolean) => void
    onTimeUpdate?: (time: number) => void
    onDurationChange?: (duration: number) => void
    onRegionUpdate?: (regionId: string, start: number, end: number) => void
    onRegionClick?: (regionId: string) => void
}

export interface WaveformViewerRef {
    play: () => void
    pause: () => void
    seekTo: (time: number) => void
    skip: (seconds: number) => void
    playRegion: (start: number, end: number) => void
    getRegionsPlugin: () => ReturnType<typeof RegionsPlugin.create> | null
}

// Color constants
const COLORS = {
    verified: 'rgba(76, 175, 80, 0.35)',
    unverified: 'rgba(144, 202, 249, 0.35)',
    active: 'rgba(255, 193, 7, 0.5)',
    waveform: '#4db6ac',
    progress: '#00897b',
    cursor: '#fff',
}

export const WaveformViewer = forwardRef<WaveformViewerRef, WaveformViewerProps>(
    ({
        audioUrl,
        segments = [],
        activeSegmentId,
        zoom = 1,
        onPlayPause,
        onTimeUpdate,
        onDurationChange,
        onRegionUpdate,
        onRegionClick,
    }, ref) => {
        const containerRef = useRef<HTMLDivElement>(null)
        const minimapRef = useRef<HTMLDivElement>(null)
        const wavesurferRef = useRef<WaveSurfer | null>(null)
        const regionsRef = useRef<ReturnType<typeof RegionsPlugin.create> | null>(null)

        // Expose methods to parent
        useImperativeHandle(ref, () => ({
            play: () => wavesurferRef.current?.play(),
            pause: () => wavesurferRef.current?.pause(),
            seekTo: (time: number) => {
                if (wavesurferRef.current) {
                    const duration = wavesurferRef.current.getDuration()
                    if (duration > 0) {
                        wavesurferRef.current.seekTo(time / duration)
                    }
                }
            },
            skip: (seconds: number) => {
                if (wavesurferRef.current) {
                    const current = wavesurferRef.current.getCurrentTime()
                    const duration = wavesurferRef.current.getDuration()
                    const newTime = Math.max(0, Math.min(duration, current + seconds))
                    wavesurferRef.current.seekTo(newTime / duration)
                }
            },
            playRegion: (start: number, end: number) => {
                if (wavesurferRef.current) {
                    const duration = wavesurferRef.current.getDuration()
                    wavesurferRef.current.seekTo(start / duration)
                    wavesurferRef.current.play()

                    // Stop at end of region
                    const checkEnd = () => {
                        const current = wavesurferRef.current?.getCurrentTime() || 0
                        if (current >= end) {
                            wavesurferRef.current?.pause()
                            wavesurferRef.current?.un('audioprocess', checkEnd)
                        }
                    }
                    wavesurferRef.current.on('audioprocess', checkEnd)
                }
            },
            getRegionsPlugin: () => regionsRef.current,
        }))

        // Initialize WaveSurfer
        useEffect(() => {
            if (!containerRef.current) return

            // Create plugins
            const regions = RegionsPlugin.create()
            regionsRef.current = regions

            const timeline = TimelinePlugin.create({
                height: 20,
                timeInterval: 5,
                primaryLabelInterval: 10,
                style: {
                    fontSize: '11px',
                    color: 'rgba(255, 255, 255, 0.6)',
                },
            })

            // Use any[] for mixed plugin types - wavesurfer.js types aren't perfectly aligned
            const plugins: any[] = [regions, timeline]

            // Add minimap if container exists
            if (minimapRef.current) {
                const minimap = MinimapPlugin.create({
                    container: minimapRef.current,
                    height: 30,
                    waveColor: 'rgba(77, 182, 172, 0.3)',
                    progressColor: 'rgba(0, 137, 123, 0.5)',
                })
                plugins.push(minimap)
            }

            // Create WaveSurfer instance
            const wavesurfer = WaveSurfer.create({
                container: containerRef.current,
                waveColor: COLORS.waveform,
                progressColor: COLORS.progress,
                cursorColor: COLORS.cursor,
                cursorWidth: 2,
                height: 'auto',
                barWidth: 2,
                barGap: 1,
                barRadius: 2,
                normalize: true,
                plugins,
            })

            wavesurferRef.current = wavesurfer

            // Load audio
            wavesurfer.load(audioUrl)

            // Event handlers
            wavesurfer.on('play', () => onPlayPause?.(true))
            wavesurfer.on('pause', () => onPlayPause?.(false))
            wavesurfer.on('finish', () => onPlayPause?.(false))

            wavesurfer.on('audioprocess', () => {
                onTimeUpdate?.(wavesurfer.getCurrentTime())
            })

            wavesurfer.on('ready', () => {
                onDurationChange?.(wavesurfer.getDuration())
            })

            // Region events
            regions.on('region-updated', (region: Region) => {
                onRegionUpdate?.(region.id, region.start, region.end)
            })

            regions.on('region-clicked', (region: Region, e: MouseEvent) => {
                e.stopPropagation()
                onRegionClick?.(region.id)

                // Play region on click
                wavesurfer.seekTo(region.start / wavesurfer.getDuration())
            })

            // Cleanup
            return () => {
                wavesurfer.destroy()
            }
        }, [audioUrl])

        // Handle zoom changes
        useEffect(() => {
            if (wavesurferRef.current) {
                wavesurferRef.current.zoom(zoom * 50)
            }
        }, [zoom])

        // Update regions when segments change
        useEffect(() => {
            const wavesurfer = wavesurferRef.current
            const regions = regionsRef.current

            if (!wavesurfer || !regions) return

            const updateRegions = () => {
                // Clear existing regions
                regions.clearRegions()

                // Add regions for each segment
                segments.forEach((segment) => {
                    const isActive = segment.id === activeSegmentId

                    regions.addRegion({
                        id: segment.id.toString(),
                        start: segment.start_time_relative,
                        end: segment.end_time_relative,
                        color: isActive
                            ? COLORS.active
                            : segment.is_verified
                                ? COLORS.verified
                                : COLORS.unverified,
                        drag: true,
                        resize: true,
                        content: segment.transcript.substring(0, 30) + (segment.transcript.length > 30 ? '...' : ''),
                    })
                })
            }

            // Update on ready or immediately if already ready
            if (wavesurfer.getDuration() > 0) {
                updateRegions()
            } else {
                wavesurfer.on('ready', updateRegions)
            }
        }, [segments, activeSegmentId])

        // Update active region highlighting
        useEffect(() => {
            const regions = regionsRef.current
            if (!regions) return

            // Update region colors based on active state
            segments.forEach((segment) => {
                const region = regions.getRegions().find(r => r.id === segment.id.toString())
                if (region) {
                    const isActive = segment.id === activeSegmentId
                    region.setOptions({
                        color: isActive
                            ? COLORS.active
                            : segment.is_verified
                                ? COLORS.verified
                                : COLORS.unverified,
                    })
                }
            })
        }, [activeSegmentId, segments])

        return (
            <Box sx={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
                {/* Main waveform */}
                <Box
                    ref={containerRef}
                    sx={{
                        flex: 1,
                        minHeight: 100,
                        '& wave': {
                            overflow: 'hidden !important',
                        },
                    }}
                />

                {/* Minimap */}
                <Box
                    ref={minimapRef}
                    sx={{
                        height: 30,
                        mt: 1,
                        borderRadius: 1,
                        overflow: 'hidden',
                        bgcolor: 'rgba(0, 0, 0, 0.2)',
                    }}
                />
            </Box>
        )
    }
)

WaveformViewer.displayName = 'WaveformViewer'
