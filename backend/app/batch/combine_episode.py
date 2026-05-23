import wave
import os
import subprocess

episodes_dir = '/app/data/episodes/2026-05-24'
lines_dir = os.path.join(episodes_dir, 'lines')
output_path = os.path.join(episodes_dir, 'episode.wav')

wav_files = sorted([f for f in os.listdir(lines_dir) if f.endswith('.wav')])
print(f"Found {len(wav_files)} WAV files: {wav_files}")

with wave.open(output_path, 'w') as out_wav:
    for i, wav_file in enumerate(wav_files):
        filepath = os.path.join(lines_dir, wav_file)
        with wave.open(filepath, 'r') as in_wav:
            params = in_wav.getparams()
            if i == 0:
                out_wav.setparams(params)
            frames = in_wav.readframes(in_wav.getnframes())
            out_wav.writeframes(frames)

print(f"Combined WAV saved to {output_path}")
file_size = os.path.getsize(output_path)
print(f"File size: {file_size / 1024:.1f} KB")

# Convert to MP3 using ffmpeg
mp3_path = os.path.join(episodes_dir, 'episode.mp3')
result = subprocess.run(
    ['ffmpeg', '-y', '-i', output_path, '-acodec', 'libmp3lame', '-b:a', '192k', mp3_path],
    capture_output=True, text=True
)
if result.returncode == 0:
    mp3_size = os.path.getsize(mp3_path)
    print(f"MP3 saved to {mp3_path} ({mp3_size / 1024:.1f} KB)")
else:
    print(f"FFmpeg error: {result.stderr}")
