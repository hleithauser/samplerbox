import os
import subprocess

# Define the folder containing WAV files
wav_folder = "/home/hl/SamplerBox/samples/what"

# Ensure the directory exists
if not os.path.exists(wav_folder):
    print(f"ERROR: Directory {wav_folder} does not exist!")
    exit(1)

# Get a list of all WAV files in the folder
wav_files = [f for f in os.listdir(wav_folder) if f.endswith(".wav")]

# Convert each file
for wav_file in wav_files:
    input_path = os.path.join(wav_folder, wav_file)
    output_path = os.path.join(wav_folder, f"fixed_{wav_file}")

    print(f"Converting: {wav_file} -> {output_path}")

    # Run ffmpeg to force a correct WAV format
    subprocess.run([
        "ffmpeg", "-y", "-i", input_path, 
        "-f", "wav", "-acodec", "pcm_s16le", "-ar", "44100", "-ac", "2", 
        output_path
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    # Replace original file with the converted one
    os.replace(output_path, input_path)

print("All WAV files have been converted successfully!")
