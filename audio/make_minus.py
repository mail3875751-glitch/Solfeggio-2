#!/usr/bin/env python3
"""Собирает минус из Shuffle_100bpm.mp3 в заданном темпе и с заданным числом квадратов.

Оригинал: 2 такта отсчёта + три одинаковых 12-тактовых квадрата + финальный удар.
Скрипт нарезает его на блоки, выкладывает нужное число квадратов подряд (чередуя
три записи, чтобы не гонять один и тот же кусок), склеивает 6-мс equal-power
кроссфейдом в тихом месте перед каждой сильной долей и растягивает по времени.

Нужны: ffmpeg с librubberband, numpy, soundfile.
"""
import argparse, subprocess, tempfile, os, sys
import numpy as np, soundfile as sf

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "Shuffle_100bpm.mp3")
DELAY = 1088          # задержка mp3-кодера, сэмплы
BAR = 2.4             # такт 4/4 при 100 BPM, с
XFADE = 0.006         # длина склейки, с
TARGET_PEAK = 0.989   # -0.1 dBFS, запас на overshoot mp3-декодера
RUBBERBAND = ("transients=crisp:detector=percussive:window=short"
              ":phase=independent:channels=together:pitchq=quality:smoothing=off")


def ffmpeg(*args):
    subprocess.run(["ffmpeg", "-v", "error", "-y", *args], check=True)


def decode_source(work):
    """Декодирует оригинал и снимает задержку кодера, чтобы доля 1 села на 0.000 с."""
    wav = os.path.join(work, "src.wav")
    ffmpeg("-i", SRC, "-af", f"atrim=start_sample={DELAY},asetpts=N/SR/TB",
           "-c:a", "pcm_f32le", wav)
    return sf.read(wav, dtype="float64")


def assemble(x, sr, squares):
    """Склеивает отсчёт + squares квадратов + финальный удар."""
    xf = int(XFADE * sr)
    bar = lambda n: int(n * BAR * sr)
    intro = (0, bar(2))
    cycles = [(bar(2), bar(14)), (bar(14), bar(26)), (bar(26), bar(38))]
    ending = (bar(38), len(x))

    plan = [intro] + [cycles[i % 3] for i in range(squares)] + [ending]
    out = [x[plan[0][0]:plan[0][1]]]
    t = np.linspace(0, 1, xf)[:, None]
    for start, end in plan[1:]:
        prev = out[-1]
        # последние xf сэмплов предыдущего блока смешиваем с тем, что в оригинале
        # звучало прямо перед сильной долей нового блока — сама доля не тронута
        out[-1] = prev[:-xf]
        out.append(prev[-xf:] * np.cos(t * np.pi / 2) + x[start - xf:start] * np.sin(t * np.pi / 2))
        out.append(x[start:end])
    return np.concatenate(out)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--bpm", type=int, default=120)
    p.add_argument("--squares", type=int, default=2)
    p.add_argument("--out")
    a = p.parse_args()
    if a.squares < 1:
        sys.exit("--squares должно быть >= 1")
    out = a.out or os.path.join(HERE, f"Shuffle_{a.bpm}bpm_{a.squares}sq.mp3")

    with tempfile.TemporaryDirectory() as work:
        x, sr = decode_source(work)
        cut = assemble(x, sr, a.squares)
        cut_wav = os.path.join(work, "cut.wav")
        sf.write(cut_wav, cut, sr, subtype="FLOAT")

        src_wav, gain = cut_wav, TARGET_PEAK / np.abs(cut).max()
        if a.bpm != 100:
            src_wav = os.path.join(work, "stretched.wav")
            ffmpeg("-i", cut_wav, "-af", f"rubberband=tempo={a.bpm / 100}:{RUBBERBAND}",
                   "-c:a", "pcm_f32le", src_wav)
            gain = TARGET_PEAK / np.abs(sf.read(src_wav)[0]).max()

        title = f"Shuffle {a.bpm} bpm ({a.squares} squares)"
        ffmpeg("-i", src_wav, "-af", f"volume={gain}", "-c:a", "libmp3lame", "-b:a", "320k",
               "-ar", "44100", "-ac", "2", "-metadata", f"title={title}",
               "-metadata", f"comment=2-bar count-in + {a.squares} x 12 bars",
               "-id3v2_version", "3", out)

    bars = 2 + 12 * a.squares
    print(f"{out}: {bars} тактов, {bars * 240 / a.bpm:.4f} с музыки + затухание")


if __name__ == "__main__":
    main()
