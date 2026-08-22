#!/usr/bin/env bash
# Пересобирает весь комплект минусов из Shuffle_100bpm.mp3.
# Нужны: ffmpeg с librubberband, python3 с numpy и soundfile.
set -euo pipefail
cd "$(dirname "$0")"

for bpm in 100 120 140; do
  ./make_minus.py --bpm "$bpm" --squares 2
done
./make_minus.py --bpm 120 --squares 10

# Любая другая комбинация: ./make_minus.py --bpm 90 --squares 6
