import subprocess
import datetime
import os

# Folder output
output_dir = "/home/tedes/datalogs_speedsign"
os.makedirs(output_dir, exist_ok=True)

# Durasi rekaman default (detik)
RECORD_DURATION = 10  

def start_recording(duration=RECORD_DURATION):
    """Mulai merekam stream RTSP dengan ffmpeg"""
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = os.path.join(output_dir, f"SAM01_record_{timestamp}.mp4")

    ffmpeg_cmd = [
        "ffmpeg",
        "-rtsp_transport", "tcp",
        "-i", "rtsp://admin:tedes2025@192.168.11.64:554/Streaming/Channels/102",
        "-c", "copy",
        "-t", str(duration),
        "-use_wallclock_as_timestamps", "1",
        "-reset_timestamps", "1",
        "-flags", "+global_header",
        output_file
    ]

    print(f"[INFO] Mulai merekam: {output_file}")
    subprocess.Popen(ffmpeg_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print(f"[INFO] Rekaman selesai: {output_file}")

