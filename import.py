import os

sample_dir = "/home/hl/SamplerBox/samples/what"
sample_file = "60.wav"

# Construct the full path
file_path = os.path.join(sample_dir, sample_file)

# Check if the file exists
if os.path.isfile(file_path):
    print(f"Found: {file_path}")
else:
    print(f"Not found: {file_path}")
