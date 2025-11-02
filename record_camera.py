import subprocess
import datetime
import os
import json

# Folder output
output_dir = "/home/tedes/datalogs_speedsign"
config_file = os.path.join(output_dir, "config.json")
os.makedirs(output_dir, exist_ok=True)


def load_record_duration(default=10):
    """Ambil nilai 'record' dari config.json, jika gagal gunakan default."""
    try:
        if os.path.exists(config_file):
            with open(config_file, "r") as f:
                cfg = json.load(f)
            if "record" in cfg:
                return int(cfg["record"])
        print(f"[WARN] config.json tidak ditemukan atau tidak ada 'record', gunakan default {default}s")
    except Exception as e:
        print(f"[ERROR] Gagal membaca config.json: {e}")
    return default


# Ambil durasi dari config.json saat program mulai
RECORD_DURATION = load_record_duration()

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

    print(f"[INFO] Mulai merekam: {output_file} (durasi {duration}s)")
    subprocess.Popen(ffmpeg_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print(f"[INFO] Rekaman selesai: {output_file}")
