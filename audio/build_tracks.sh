#!/usr/bin/env bash
# Собирает минусы из исходника Shuffle_100bpm.mp3.
# Требуется ffmpeg, собранный с librubberband, и python3 с numpy/soundfile.
set -euo pipefail
cd "$(dirname "$0")"

SRC=Shuffle_100bpm.mp3
WORK=$(mktemp -d); trap 'rm -rf "$WORK"' EXIT
RB=transients=crisp:detector=percussive:window=short:phase=independent:channels=together:pitchq=quality:smoothing=off
TARGET=0.989   # -0.1 dBFS, запас на overshoot mp3-декодера

# 1. Декод + снятие задержки mp3-кодера (1088 сэмплов), чтобы доля 1 села на 0.000 с
ffmpeg -v error -y -i "$SRC" -af "atrim=start_sample=1088,asetpts=N/SR/TB" -c:a pcm_f32le "$WORK/src.wav"

# 2. Обрезка до 2 квадратов: такты 1-26 + финальный удар из такта 39 (склейка 6 мс equal-power)
python3 - "$WORK/src.wav" "$WORK/cut.wav" <<'PY'
import sys, numpy as np, soundfile as sf
x, sr = sf.read(sys.argv[1], dtype='float64')
bar = 2.4                                  # 4/4 при 100 BPM
cut, tail, xf = int(26*bar*sr), int(38*bar*sr), int(0.006*sr)
t = np.linspace(0, 1, xf)[:, None]
out = np.empty((cut + len(x) - tail, 2))
out[:cut-xf] = x[:cut-xf]
out[cut-xf:cut] = x[cut-xf:cut]*np.cos(t*np.pi/2) + x[tail-xf:tail]*np.sin(t*np.pi/2)
out[cut:] = x[tail:]
sf.write(sys.argv[2], out, sr, subtype='FLOAT')
PY

# 3. Растяжение по времени и экспорт
ffmpeg -v error -y -i "$WORK/cut.wav" -c:a libmp3lame -b:a 320k \
  -metadata title="Shuffle 100 bpm (2 squares)" -id3v2_version 3 Shuffle_100bpm_2sq.mp3

for bpm in 120 140; do
  ffmpeg -v error -y -i "$WORK/cut.wav" -af "rubberband=tempo=$(bc -l <<<"$bpm/100"):$RB" \
    -c:a pcm_f32le "$WORK/st.wav"
  gain=$(python3 -c "import soundfile as sf,numpy as np;x,_=sf.read('$WORK/st.wav');print($TARGET/abs(x).max())")
  ffmpeg -v error -y -i "$WORK/st.wav" -af "volume=$gain" -c:a libmp3lame -b:a 320k \
    -metadata title="Shuffle $bpm bpm (2 squares)" -id3v2_version 3 "Shuffle_${bpm}bpm_2sq.mp3"
done
