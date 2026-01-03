#!/bin/bash

# Recursively find all .mp4 and .mkv files, skipping hidden/system files
find ./ -type f \( -iname "*.mp4" -o -iname "*.mkv" \) ! -name ".*" | while read -r file; do
  # Skip unreadable or non-writable files
  if [ ! -w "$file" ]; then
    echo "⚠️ Skipping '$file': no write permission"
    continue
  fi

  # Remove all existing tags
  tag -r "$file"

  # Extract parent folders (excluding "." and "./videos")
  parent_dirs=$(dirname "$file" | tr '/' '\n' | grep -vE '^\.$|^videos$')

  # Collect tags exactly as-is
  tags=()
  while read -r dir; do
    tags+=("$dir")
  done <<< "$parent_dirs"

  # Apply each tag
  for tagname in "${tags[@]}"; do
    tag -a "$tagname" "$file"
  done

  echo "✅ Tagged '$file' with: ${tags[*]}"
done

echo "🎉 All tagging complete!"

