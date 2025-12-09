import { useEffect, useRef, forwardRef, useImperativeHandle } from 'react'
import WaveSurfer from 'wavesurfer.js'
import RegionsPlugin from 'wavesurfer.js/dist/plugins/regions.esm.js'
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
    onPlayPause?: (isPlaying: boolean) => void
    segments?: Segment[]
}

export interface WaveformViewerRef {
    play: () => void
    pause: () => void
    seekTo: (time: number) => void
}

export const WaveformViewer = forwardRef<WaveformViewerRef, WaveformViewerProps>(
    ({ audioUrl, onPlayPause, segments = [] }, ref) => {
        const containerRef = useRef<HTMLDivElement>(null)
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
        }))

        // Initialize WaveSurfer
        useEffect(() => {
            if (!containerRef.current) return

            // Create regions plugin
            const regions = RegionsPlugin.create()
            regionsRef.current = regions

            // Create WaveSurfer instance
            const wavesurfer = WaveSurfer.create({
                container: containerRef.current,
                waveColor: '#4db6ac',
                progressColor: '#00897b',
                cursorColor: '#fff',
                height: 128,
                barWidth: 2,
                barGap: 1,
                barRadius: 2,
                plugins: [regions],
            })

            wavesurferRef.current = wavesurfer

            // Load audio
            wavesurfer.load(audioUrl)

            // Event handlers
            wavesurfer.on('play', () => onPlayPause?.(true))
            wavesurfer.on('pause', () => onPlayPause?.(false))
            wavesurfer.on('finish', () => onPlayPause?.(false))

            // Cleanup
            return () => {
                wavesurfer.destroy()
            }
        }, [audioUrl, onPlayPause])

        // Update regions when segments change
        useEffect(() => {
            if (!regionsRef.current || !wavesurferRef.current) return

            // Wait for audio to load
            wavesurferRef.current.on('ready', () => {
                // Clear existing regions
                regionsRef.current?.clearRegions()

                // Add regions for each segment
                segments.forEach((segment) => {
                    regionsRef.current?.addRegion({
                        id: segment.id.toString(),
                        start: segment.start_time_relative,
                        end: segment.end_time_relative,
                        color: segment.is_verified
                            ? 'rgba(76, 175, 80, 0.3)'  // Green for verified
                            : 'rgba(144, 202, 249, 0.3)', // Blue for unverified
                        drag: true,
                        resize: true,
                    })
                })
            })
        }, [segments])

        return (
            <Box
                ref={containerRef}
                sx={{
                    width: '100%',
                    bgcolor: 'rgba(0, 0, 0, 0.2)',
                    borderRadius: 1,
                    overflow: 'hidden',
                }}
            />
        )
    }
)

WaveformViewer.displayName = 'WaveformViewer'
