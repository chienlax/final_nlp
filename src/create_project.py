#!/usr/bin/env python3
"""
Create Label Studio projects with templates.

Usage:
    python src/create_project.py --task-type transcript_correction
    python src/create_project.py --task-type translation_review
    python src/create_project.py --task-type audio_segmentation
"""

import os
import sys
import argparse
from pathlib import Path
import requests

# Task type to template file mapping
TASK_TEMPLATES = {
    "transcript_correction": "transcript_correction.xml",
    "translation_review": "translation_review.xml",
    "audio_segmentation": "audio_segmentation.xml",
    "segment_review": "segment_review.xml",
}

# Task type to project name mapping
TASK_PROJECT_NAMES = {
    "transcript_correction": "Transcript Correction",
    "translation_review": "Translation Review",
    "audio_segmentation": "Audio Segmentation",
    "segment_review": "Segment Review",
}


def create_project(task_type: str, ls_url: str, api_key: str) -> dict:
    """
    Create a Label Studio project for the given task type.
    
    Args:
        task_type: Type of annotation task
        ls_url: Label Studio URL
        api_key: API authentication token
        
    Returns:
        dict: Created project data
    """
    # Get template file
    template_file = TASK_TEMPLATES.get(task_type)
    if not template_file:
        print(f"❌ Unknown task type: {task_type}")
        print(f"   Available: {', '.join(TASK_TEMPLATES.keys())}")
        sys.exit(1)
    
    # Find template path
    templates_dir = Path(__file__).parent.parent / "label_studio_templates"
    template_path = templates_dir / template_file
    
    if not template_path.exists():
        print(f"❌ Template file not found: {template_path}")
        sys.exit(1)
    
    # Read template
    label_config = template_path.read_text(encoding="utf-8")
    project_name = TASK_PROJECT_NAMES.get(task_type, task_type)
    
    print(f"📝 Creating project: {project_name}")
    print(f"   Template: {template_file}")
    
    # Create project via API
    headers = {"Authorization": f"Token {api_key}"}
    data = {
        "title": project_name,
        "label_config": label_config,
    }
    
    response = requests.post(
        f"{ls_url}/api/projects",
        headers=headers,
        json=data,
        timeout=30
    )
    
    if response.status_code == 201:
        project = response.json()
        print(f"✅ Project created successfully!")
        print(f"   ID: {project['id']}")
        print(f"   Title: {project['title']}")
        return project
    else:
        print(f"❌ Failed to create project")
        print(f"   Status: {response.status_code}")
        print(f"   Error: {response.text[:500]}")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="Create Label Studio projects")
    parser.add_argument(
        "--task-type",
        choices=list(TASK_TEMPLATES.keys()),
        required=True,
        help="Type of annotation task"
    )
    parser.add_argument(
        "--ls-url",
        default=os.environ.get("LABEL_STUDIO_URL", "http://localhost:8085"),
        help="Label Studio URL"
    )
    parser.add_argument(
        "--api-key",
        default=os.environ.get("LABEL_STUDIO_API_KEY"),
        help="Label Studio API key"
    )
    
    args = parser.parse_args()
    
    if not args.api_key:
        print("❌ LABEL_STUDIO_API_KEY not set")
        sys.exit(1)
    
    print("=" * 60)
    print("Create Label Studio Project")
    print("=" * 60)
    print(f"Label Studio URL: {args.ls_url}")
    print(f"Task Type: {args.task_type}")
    print()
    
    create_project(args.task_type, args.ls_url, args.api_key)


if __name__ == "__main__":
    main()
