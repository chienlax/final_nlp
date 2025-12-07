# Documentation Index

Consolidated documentation for the NLP Code-Switching Speech Translation project.

## 📚 Current Documentation (2 Files)

### 1. **docs/USER_GUIDE.md** - End-User Manual
**Target Audience**: Reviewers, QA testers, non-technical users

**Contents**:
- Quick start guide
- Web interface tutorial (Dashboard, Review, Upload, Refinement, Download tabs)
- Keyboard shortcuts
- End-to-end workflow
- Troubleshooting common issues

**When to use**: 
- First time using the review interface
- Learning how to review transcriptions
- Understanding the data pipeline workflow

---

### 2. **docs/DEVELOPER_GUIDE.md** - Technical Reference
**Target Audience**: Developers, MLOps engineers, contributors

**Contents**:
- System architecture
- Technology stack
- Database schema
- NiceGUI framework constraints and patterns
- Core modules (preprocessing, database, GUI)
- API reference
- Development workflow
- Testing and deployment

**When to use**:
- Contributing code to the project
- Understanding technical implementation
- Debugging issues
- Extending functionality

---

### 3. **docs/WORKFLOW.md** - Pipeline Reference
**Target Audience**: Data engineers, ML engineers

**Contents**:
- Detailed pipeline stages (ingestion → preprocessing → transcription → review → export)
- Command-line tool usage
- Data formats and standards
- Integration points

**When to use**:
- Running the full pipeline
- Understanding data flow
- Integrating with training workflows

---

## 🗂️ Archived Documentation

The following docs have been **consolidated** and moved to `archive/`:

- `archive/UI_GUIDE.md` → Merged into **USER_GUIDE.md**
- `archive/DEVELOPER.md` → Merged into **DEVELOPER_GUIDE.md**
- `archive/NICEGUI_MIGRATION.md` → Merged into **DEVELOPER_GUIDE.md** (NiceGUI section)
- `archive/IMPLEMENTATION_SUMMARY.md` → Merged into **DEVELOPER_GUIDE.md** (Architecture section)

These files are kept for historical reference but are **no longer maintained**.

---

## 🎯 Quick Reference

**I want to...**

| Task | Documentation |
|------|---------------|
| Learn how to use the review interface | **USER_GUIDE.md** |
| Review transcriptions | **USER_GUIDE.md** → Review Tab |
| Export approved data | **USER_GUIDE.md** → Download Tab |
| Understand keyboard shortcuts | **USER_GUIDE.md** → Keyboard Shortcuts |
| Run the full pipeline | **WORKFLOW.md** |
| Contribute code | **DEVELOPER_GUIDE.md** |
| Understand database schema | **DEVELOPER_GUIDE.md** → Database Schema |
| Fix NiceGUI routing issues | **DEVELOPER_GUIDE.md** → Troubleshooting |
| Add new features to GUI | **DEVELOPER_GUIDE.md** → NiceGUI Application |
| Deploy to production | **DEVELOPER_GUIDE.md** → Deployment |

---

## 📝 Documentation Standards

When updating documentation:

1. **Single Source of Truth**: Avoid duplicating information across files
2. **Cross-Reference**: Link between docs using relative paths
3. **Keep Examples Up-to-Date**: Test all code snippets before committing
4. **Use Clear Headings**: Enable quick navigation with ToC
5. **Update This Index**: When adding new docs, update this file

---

## 🔄 Recent Changes (v2.0 - 2025-01-15)

### What Changed

**Consolidated 5 docs → 2 main docs**:
- Created comprehensive **USER_GUIDE.md** (end-user manual)
- Created comprehensive **DEVELOPER_GUIDE.md** (technical reference)
- Kept **WORKFLOW.md** as pipeline-specific reference
- Archived 4 outdated/redundant docs

### Why

**Problems with old structure**:
- Information scattered across 5+ files
- Duplicate content (routing explained in 3 places)
- Outdated info (URL routing docs for non-working feature)
- Hard to find answers quickly

**Benefits of new structure**:
- **2 main docs** = faster navigation
- Clear audience targeting (users vs developers)
- Single source of truth for each topic
- Updated with latest architecture (tab-based navigation)

---

## 🚀 Getting Started

### For End-Users

1. Read **USER_GUIDE.md** → Quick Start
2. Launch application
3. Follow tutorial for each tab
4. Refer back for keyboard shortcuts and troubleshooting

### For Developers

1. Read **DEVELOPER_GUIDE.md** → Architecture Overview
2. Set up development environment
3. Understand NiceGUI constraints (important!)
4. Follow development workflow for contributions

---

## 📞 Support

**Can't find what you're looking for?**

1. Check this index for the right doc
2. Use Ctrl+F to search within docs
3. Check archived docs for historical context
4. Open GitHub issue for documentation improvements

---

**Last Updated**: 2025-01-15  
**Version**: 2.0  
**Maintainer**: MLOps Team
