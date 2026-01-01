#!/bin/bash
set -e

# Clean previous builds
rm -rf dist/ build/ *.egg-info

# Build package
python -m build

# Check package
twine check dist/*

# Upload to PyPI
twine upload dist/*
