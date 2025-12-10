"""
YouTube Ingestion GUI - Tkinter Client.

Standalone GUI for downloading YouTube videos/playlists and uploading to the server.
Performs duplicate detection before download.

Features:
    - URL input with validation
    - Playlist expansion with video selection
    - Duplicate checking against database
    - Progress feedback during download
    - Upload to FastAPI server

Usage:
    python ingest_gui.py
"""

import os
import sys
import threading
from pathlib import Path
from typing import Optional, List
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

import requests

from backend.ingestion.downloader import (
    fetch_metadata, 
    fetch_playlist_metadata, 
    download_audio,
    VideoMetadata
)


# =============================================================================
# CONFIGURATION
# =============================================================================

API_BASE = os.getenv("API_BASE", "http://localhost:8000/api")
DATA_ROOT = Path(os.getenv("DATA_ROOT", "./data"))
TEMP_DIR = DATA_ROOT / "temp"


# =============================================================================
# API FUNCTIONS
# =============================================================================

def check_duplicate(url: str) -> dict:
    """Check if URL already exists in database."""
    try:
        resp = requests.get(f"{API_BASE}/videos/check", params={"url": url})
        return resp.json()
    except Exception as e:
        return {"exists": False, "message": str(e)}


def get_users() -> List[dict]:
    """Fetch user list from API."""
    try:
        resp = requests.get(f"{API_BASE}/users")
        resp.raise_for_status()
        data = resp.json()
        # Defensive: ensure it's a list
        return data if isinstance(data, list) else []
    except Exception:
        return []


def get_channels() -> List[dict]:
    """Fetch channel list from API."""
    try:
        resp = requests.get(f"{API_BASE}/channels")
        resp.raise_for_status()
        data = resp.json()
        # Defensive: ensure it's a list
        if isinstance(data, list) and len(data) > 0:
            return data
        return [{"id": 1, "name": "Default"}]
    except Exception:
        return [{"id": 1, "name": "Default"}]


def upload_video(
    file_path: Path,
    title: str,
    duration: int,
    url: str,
    channel_id: int,
    user_id: int
) -> dict:
    """Upload video to server."""
    try:
        with open(file_path, "rb") as f:
            resp = requests.post(
                f"{API_BASE}/videos/upload",
                headers={"X-User-ID": str(user_id)},
                files={"audio": (file_path.name, f, "audio/mp4")},
                data={
                    "title": title,
                    "duration_seconds": duration,
                    "original_url": url,
                    "channel_id": channel_id,
                }
            )
        return resp.json()
    except Exception as e:
        return {"error": str(e)}


# =============================================================================
# GUI APPLICATION
# =============================================================================

class IngestGUI:
    """YouTube ingestion GUI application."""
    
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("🎙️ Speech Translation - YouTube Ingestion")
        self.root.geometry("800x600")
        self.root.resizable(True, True)
        
        # Configure style
        style = ttk.Style()
        style.configure("TFrame", background="#1e3a5f")
        style.configure("TLabel", background="#1e3a5f", foreground="white")
        style.configure("TButton", padding=6)
        
        # Data
        self.videos: List[VideoMetadata] = []
        self.users = get_users()
        self.channels = get_channels()
        
        self._build_ui()
    
    def _build_ui(self):
        """Build the user interface."""
        # Main container
        main = ttk.Frame(self.root, padding=10)
        main.pack(fill=tk.BOTH, expand=True)
        
        # ========== Top Section: URL Input ==========
        url_frame = ttk.LabelFrame(main, text="YouTube URL", padding=10)
        url_frame.pack(fill=tk.X, pady=(0, 10))
        
        self.url_entry = ttk.Entry(url_frame, width=60)
        self.url_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 10))
        self.url_entry.bind("<Return>", lambda e: self._fetch_videos())
        
        ttk.Button(url_frame, text="Fetch", command=self._fetch_videos).pack(side=tk.LEFT)
        
        # ========== User/Channel Selection ==========
        select_frame = ttk.Frame(main)
        select_frame.pack(fill=tk.X, pady=(0, 10))
        
        ttk.Label(select_frame, text="User:").pack(side=tk.LEFT, padx=(0, 5))
        self.user_var = tk.StringVar()
        self.user_combo = ttk.Combobox(
            select_frame, 
            textvariable=self.user_var,
            values=[u["username"] for u in self.users],
            width=15
        )
        self.user_combo.pack(side=tk.LEFT, padx=(0, 20))
        if self.users:
            self.user_combo.current(0)
        
        ttk.Label(select_frame, text="Channel:").pack(side=tk.LEFT, padx=(0, 5))
        self.channel_var = tk.StringVar()
        self.channel_combo = ttk.Combobox(
            select_frame,
            textvariable=self.channel_var,
            values=[c["name"] for c in self.channels],
            width=20
        )
        self.channel_combo.pack(side=tk.LEFT)
        if self.channels:
            self.channel_combo.current(0)
        
        # ========== Video List ==========
        list_frame = ttk.LabelFrame(main, text="Videos", padding=10)
        list_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 10))
        
        # Treeview for video list
        columns = ("title", "duration", "status")
        self.tree = ttk.Treeview(list_frame, columns=columns, show="headings", selectmode="extended")
        self.tree.heading("title", text="Title")
        self.tree.heading("duration", text="Duration")
        self.tree.heading("status", text="Status")
        self.tree.column("title", width=400)
        self.tree.column("duration", width=80)
        self.tree.column("status", width=150)
        
        scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        # ========== Actions ==========
        action_frame = ttk.Frame(main)
        action_frame.pack(fill=tk.X, pady=(0, 10))
        
        ttk.Button(action_frame, text="Select All", command=self._select_all).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(action_frame, text="Check Duplicates", command=self._check_duplicates).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(action_frame, text="Download Selected", command=self._download_selected).pack(side=tk.LEFT)
        
        # ========== Log Output ==========
        log_frame = ttk.LabelFrame(main, text="Log", padding=5)
        log_frame.pack(fill=tk.X)
        
        self.log = scrolledtext.ScrolledText(log_frame, height=6, state=tk.DISABLED)
        self.log.pack(fill=tk.X)
    
    def _log(self, message: str):
        """Add message to log."""
        self.log.configure(state=tk.NORMAL)
        self.log.insert(tk.END, f"{message}\n")
        self.log.see(tk.END)
        self.log.configure(state=tk.DISABLED)
    
    def _fetch_videos(self):
        """Fetch video metadata from URL."""
        url = self.url_entry.get().strip()
        if not url:
            messagebox.showwarning("Error", "Please enter a URL")
            return
        
        self._log(f"Fetching: {url}")
        self.tree.delete(*self.tree.get_children())
        self.videos.clear()
        
        def fetch():
            videos = fetch_playlist_metadata(url)
            self.root.after(0, lambda: self._update_video_list(videos))
        
        threading.Thread(target=fetch, daemon=True).start()
    
    def _update_video_list(self, videos: List[VideoMetadata]):
        """Update video list in UI."""
        self.videos = videos
        
        for video in videos:
            duration_str = f"{video.duration_seconds // 60}:{video.duration_seconds % 60:02d}"
            self.tree.insert("", tk.END, values=(video.title, duration_str, "Ready"))
        
        self._log(f"Found {len(videos)} videos")
    
    def _select_all(self):
        """Select all videos in list."""
        for item in self.tree.get_children():
            self.tree.selection_add(item)
    
    def _check_duplicates(self):
        """Check selected videos for duplicates."""
        selection = self.tree.selection()
        if not selection:
            messagebox.showwarning("Error", "Please select videos first")
            return
        
        self._log("Checking for duplicates...")
        
        for item in selection:
            idx = self.tree.index(item)
            video = self.videos[idx]
            
            result = check_duplicate(video.original_url)
            
            if result.get("exists"):
                self.tree.set(item, "status", "⚠️ Duplicate")
            else:
                self.tree.set(item, "status", "✓ OK")
        
        self._log("Duplicate check complete")
    
    def _download_selected(self):
        """Download selected videos."""
        selection = self.tree.selection()
        if not selection:
            messagebox.showwarning("Error", "Please select videos first")
            return
        
        # Get user and channel
        user_idx = self.user_combo.current()
        channel_idx = self.channel_combo.current()
        
        if user_idx < 0 or channel_idx < 0:
            messagebox.showwarning("Error", "Please select user and channel")
            return
        
        user_id = self.users[user_idx]["id"]
        channel_id = self.channels[channel_idx]["id"]
        
        TEMP_DIR.mkdir(parents=True, exist_ok=True)
        
        def download_all():
            for item in selection:
                idx = self.tree.index(item)
                video = self.videos[idx]
                
                # Skip duplicates
                status = self.tree.set(item, "status")
                if "Duplicate" in status:
                    self._log(f"Skipping duplicate: {video.title}")
                    continue
                
                self.root.after(0, lambda i=item: self.tree.set(i, "status", "⏳ Downloading..."))
                
                # Download
                result = download_audio(
                    video.original_url,
                    TEMP_DIR,
                    lambda msg: self.root.after(0, lambda m=msg: self._log(m))
                )
                
                if result and result.file_path:
                    # Upload to server
                    self.root.after(0, lambda i=item: self.tree.set(i, "status", "⏳ Uploading..."))
                    
                    upload_result = upload_video(
                        result.file_path,
                        result.title,
                        result.duration_seconds,
                        result.original_url,
                        channel_id,
                        user_id
                    )
                    
                    if "video_id" in upload_result:
                        self.root.after(0, lambda i=item: self.tree.set(i, "status", "✓ Complete"))
                        self._log(f"✓ Uploaded: {video.title}")
                    else:
                        self.root.after(0, lambda i=item: self.tree.set(i, "status", "✗ Upload failed"))
                        self._log(f"✗ Upload error: {upload_result.get('error', 'Unknown error')}")
                else:
                    self.root.after(0, lambda i=item: self.tree.set(i, "status", "✗ Download failed"))
                    self._log(f"✗ Download failed: {video.title}")
            
            self._log("Batch complete!")
        
        threading.Thread(target=download_all, daemon=True).start()


# =============================================================================
# MAIN
# =============================================================================

def main():
    """Run the ingestion GUI."""
    root = tk.Tk()
    app = IngestGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
