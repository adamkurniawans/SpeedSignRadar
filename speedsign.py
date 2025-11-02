import os
import time
import json
import serial
import netifaces
import datetime
import RPi.GPIO as GPIO
from threading import Thread
from flask import Flask, jsonify, send_from_directory, url_for, request
from rgbmatrix import RGBMatrix, RGBMatrixOptions
from PIL import Image, ImageDraw, ImageFont
from record_camera import start_recording
import subprocess

# ==============================
# Konfigurasi Folder 
# ==============================
VIDEO_FOLDER = "/home/tedes/datalogs_speedsign"
LOG_FILE = os.path.join(VIDEO_FOLDER, "SAM01_speed_log.json")
CONFIG_FILE = os.path.join(VIDEO_FOLDER, "config.json")
os.makedirs(VIDEO_FOLDER, exist_ok=True)

FONT_PATH = "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"
W, H = 32, 32  # ukuran panel P10 double atas bawah

# ==============================
# Setup Flask
# ==============================
app = Flask(__name__)
app.config["VIDEO_FOLDER"] = VIDEO_FOLDER

def show_smile():
    """Tampilkan emot senyum di panel P10 saat startup"""
    image = Image.new("RGB", (W, H), (0, 0, 0))
    draw = ImageDraw.Draw(image)

    # Wajah (lingkaran)
    draw.ellipse((2, 2, W - 3, H - 3), outline=(0, 255, 0), width=2)

    # Mata kiri & kanan
    draw.ellipse((9, 8, 13, 12), fill=(0, 255, 0))
    draw.ellipse((19, 8, 23, 12), fill=(0, 255, 0))

    # Mulut (senyum)
    draw.arc((8, 14, 24, 26), start=20, end=160, fill=(0, 255, 0), width=2)

    # Tampilkan ke panel
    matrix.SetImage(image)


def get_system_timezone():
    try:
        result = subprocess.run(
            ["timedatectl"], capture_output=True, text=True, check=True
        )

        for line in result.stdout.splitlines():
            if "Time zone" in line:
                # Contoh output:
                # " Time zone: Asia/Jakarta (WIB, +0700)"
                parts = line.split("(")
                if len(parts) > 1:
                    # Ambil bagian dalam kurung: "WIB, +0700)"
                    inner = parts[1]
                    # Pisahkan dengan koma: ["WIB", " +0700)"]
                    inner_parts = inner.split(",")
                    if len(inner_parts) > 1:
                        offset_str = inner_parts[1].strip().rstrip(")")
                        # Contoh offset_str = "+0700" atau "-0530"
                        sign = 1 if offset_str[0] == "+" else -1
                        hours = int(offset_str[1:3])
                        minutes = int(offset_str[3:5])
                        offset_number = sign * (hours + minutes / 60)
                        return offset_number
    except Exception as e:
        print(f"Gagal ambil timezone: {e}")
    return None

def get_timeserver():
    try:
        result = subprocess.run(
            ["timedatectl", "show-timesync", "--property=ServerName"],
            capture_output=True, text=True, check=True
        )
        # Contoh output: "ServerName=0.id.pool.ntp.org"
        for line in result.stdout.splitlines():
            if "ServerName=" in line:
                return line.split("=")[1].strip()
    except Exception as e:
        print(f"Gagal ambil timeserver: {e}")
    return None


# ==============================
# Utilitas Konfigurasi
# ==============================
def read_config():
    default_config = {
        "speed_limit": 60,
        "record": 10
    }

    # Jika file config belum ada ? buat dengan default
    if not os.path.exists(CONFIG_FILE):
        save_config(default_config)
        return default_config

    try:
        with open(CONFIG_FILE, "r") as f:
            data = json.load(f)

        # Tambahkan key yang belum ada
        updated = False
        for key, value in default_config.items():
            if key not in data:
                data[key] = value
                updated = True

        # Jika ada penambahan key baru ? simpan kembali
        if updated:
            save_config(data)

        return data

    except json.JSONDecodeError:
        # Jika file rusak, tulis ulang default
        save_config(default_config)
        return default_config


def save_config(config):
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2)

# ==============================
# API Endpoint
# ==============================

#program ferdi
def get_all_json_files(directory):
    json_files = []
    for root, dirs, files in os.walk(directory):
        for file in files:
            if file.endswith(".json"):
                full_path = os.path.join(root, file)
                file_info = {
                    "name": file,
                    "path": full_path,
                    "size": os.path.getsize(full_path),
                    "modifiedAt": os.path.getmtime(full_path)
                }
                json_files.append(file_info)
    return json_files

@app.route("/api/json-files", methods=["GET"])
def list_json_files():
    try:
        files = get_all_json_files(VIDEO_FOLDER)
        return jsonify({
            "success": True,
            "count": len(files),
            "files": files
        })
    except Exception as e:
        return jsonify({
            "success": False,
            "message": "Gagal membaca file JSON",
            "error": str(e)
        }), 500

@app.route("/api/json-files/<filename>", methods=["GET"])
def get_json_content(filename):
    try:
        file_path = os.path.join(VIDEO_FOLDER, filename)

        if not os.path.exists(file_path):
            return jsonify({
                "success": False,
                "message": f"File '{filename}' tidak ditemukan"
            }), 404

        # Baca isi file JSON
        with open(file_path, "r") as f:
            try:
                logs = json.load(f)
            except json.JSONDecodeError:
                return jsonify({
                    "success": False,
                    "message": f"File '{filename}' bukan JSON valid"
                }), 400

        data = []

        # Jika isi file adalah list log
        if isinstance(logs, list):
            for log_entry in logs:
                video_name = log_entry.get("video")
                if not video_name:
                    continue

                # Buat URL video
                video_url = None
                if video_name != "Tidak diRecord/sedang cooldown":
                    video_url = url_for("get_video", video=video_name, _external=True)

                data.append({
                    "video": video_name,
                    "videoUrl": video_url,
                    "speed": log_entry.get("speed"),
                    "timestamp": log_entry.get("timestamp"),
                })

        else:
            # Jika isi JSON hanya 1 objek
            video_name = logs.get("video")
            video_url = None
            if video_name and video_name != "Tidak diRecord/sedang cooldown":
                video_url = url_for("get_video", video=video_name, _external=True)

            data.append({
                "video": video_name,
                "videoUrl": video_url,
                "speed": logs.get("speed"),
                "timestamp": logs.get("timestamp"),
            })

        return jsonify({
            "success": True,
            "filename": filename,
            "count": len(data),
            "data": data
        }), 200

    except Exception as e:
        return jsonify({
            "success": False,
            "message": f"Gagal membaca isi file '{filename}'",
            "error": str(e)
        }), 500
    delayed_delete(video_path, f, delay=10)

@app.route('/api/network', methods=['GET'])
def get_eth0_info():
    interface = "eth0"
    
    # Pastikan interface eth0 ada di sistem
    if interface not in netifaces.interfaces():
        return jsonify({
            "error": f"Interface '{interface}' tidak ditemukan pada sistem"
        }), 404

    # Ambil informasi alamat IPv4
    addresses = netifaces.ifaddresses(interface)
    ipv4_info = addresses.get(netifaces.AF_INET, [])
    
    config = read_config()
    record = config.get("record", None)
    
    # Ambil speed_limit dari config
    config = read_config()
    speed_limit = config.get("speed_limit", None)  # fallback None jika belum ada
    
    # Ambil timezone & timeserver
    timezone = get_system_timezone()
    timeserver = get_timeserver()

    # Jika eth0 belum punya IP
    if not ipv4_info:
        return jsonify({
            "interface": interface,
            "ip": None,
            "subnet": None,
            "gateway": None,
            "status": "belum mendapat IP",
            "record" : record,
            "speed_limit": speed_limit,
            "timezone": timezone,
            "timeserver": timeserver
        }), 200

    ipv4 = ipv4_info[0]
    ip = ipv4.get('addr')
    subnet = ipv4.get('netmask')

    # Ambil gateway default
    gateways = netifaces.gateways()
    default_gateway = gateways.get('default', {}).get(netifaces.AF_INET, [None])[0]

    # Kirim hasil dalam JSON
    return jsonify({
        "interface": interface,
        "ip": ip,
        "subnet": subnet,
        "gateway": default_gateway,
        "status": "OK",
        "speed_limit": speed_limit,
        "record" : record,
        "timezone": timezone,
        "timeserver": timeserver
    }), 200

@app.route('/api/health', methods=['GET']) # cek status koneksi
def health_check():
    return jsonify({"status": "connected"}), 200

@app.route('/api/data', methods=['GET'])
def get_data():
    files = sorted([f for f in os.listdir(VIDEO_FOLDER) if f.endswith(".mp4")], reverse=True)
    logs = []

    if os.path.exists(LOG_FILE):
        with open(LOG_FILE, "r") as f:
            try:
                logs = json.load(f)
            except json.JSONDecodeError:
                logs = []

    data = []

    # Proses semua file video yang ada
    for f in files:
        video_path = os.path.join(VIDEO_FOLDER, f)
        video_url = url_for('get_video', video=f, _external=True)
        log_entry = next((item for item in logs if item.get("video") == f), None)

        data.append({
            "video": f,
            "videoUrl": video_url,
            "speed": log_entry.get("speed") if log_entry else None,
            "timestamp": log_entry.get("timestamp") if log_entry else None
        })

        delayed_delete(video_path, f, delay=10)

    # Tambahkan log tanpa video
    no_video_logs = [item for item in logs if item.get("video") == "Tidak diRecord/sedang cooldown"]
    for log_entry in no_video_logs:
        data.append({
            "video": log_entry.get("video"),
            "videoUrl": None,
            "speed": log_entry.get("speed"),
            "timestamp": log_entry.get("timestamp")
        })

    # Jika tidak ada file video, tetap jalankan delayed_delete untuk membersihkan log
    if not files and no_video_logs:
        print("[INFO] Tidak ada file video, hanya log cooldown")
        delayed_delete(None, "Tidak diRecord/sedang cooldown", delay=10)

    return jsonify(data), 200


@app.route('/api/config', methods=['GET', 'POST'])
def config_handler():
    if request.method == 'GET':
        return jsonify(read_config()), 200

    elif request.method == 'POST':
        config = request.json
        current = read_config()

        if "speed_limit" in config:
            current["speed_limit"] = int(config["speed_limit"])
        if "record" in config:
            current["record"] = int(config["record"])

        save_config(current)
        print(f"Config updated: speed_limit={current['speed_limit']} km/h, record={current['record']}s")
        return jsonify({
            "status": "ok",
            "message": "Configuration updated",
            "config": current
        }), 200
    
    
@app.route('/videos/<path:video>') #hapus file setalah collect data
def get_video(video):
    return send_from_directory(app.config['VIDEO_FOLDER'], video)

def delayed_delete(video_path, video_name, delay=10):
    def delete_task():
        time.sleep(delay)
        print(f"[INFO] Menghapus data setelah {delay}s")

        # Hapus file video jika ada
        try:
            if video_path and os.path.exists(video_path):
                os.remove(video_path)
                print(f"[INFO] Video {video_name} dihapus.")
        except Exception as e:
            print(f"[WARN] Gagal hapus {video_name}: {e}")

        # Kosongkan log
        if os.path.exists(LOG_FILE):
            with open(LOG_FILE, "w") as f:
                json.dump([], f, indent=2)
            print("[INFO] Log dikosongkan.")

    Thread(target=delete_task, daemon=True).start()


def log_speed(speed, with_video=False):
    
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    entry = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "speed": speed,
        "video": f"SAM01_record_{timestamp}.mp4" if with_video else "Tidak diRecord/sedang cooldown"
        
        
    }
    try:
        if os.path.exists(LOG_FILE):
            with open(LOG_FILE, "r") as f:
                data = json.load(f)
        else:
            data = []
    except json.JSONDecodeError:
        data = []
    data.append(entry)
    with open(LOG_FILE, "w") as f:
        json.dump(data, f, indent=4)


# ==============================
# Hardware Setup
# ==============================
# GPIO Relay / Lampu Indikator

pin_panel = 26 # pin fisik 37
pinON = 21 #pin fisik 36
pinrelay = 16 #pin fisik 40
GPIO.setmode(GPIO.BCM)
GPIO.setup(pinON, GPIO.OUT)
GPIO.output(pinON, GPIO.HIGH) #indikator ON

GPIO.setup(pinrelay, GPIO.IN)

GPIO.setup(pin_panel, GPIO.IN)
time.sleep(0.5)
GPIO.setup(pin_panel, GPIO.OUT)
GPIO.output(pin_panel, GPIO.LOW) #panel ON



# Serial TSR20
ser = serial.Serial("/dev/ttyUSB0", baudrate=9600, timeout=0.1)
print("Membaca data TSR20...")

# Panel P10
options = RGBMatrixOptions()
options.rows = 16
options.cols = 32
options.chain_length = 1
options.parallel = 2  #2 panel atas bawah
options.hardware_mapping = "regular"
options.row_address_type = 0
#options.multiplexing = 4  # panel riskul tidak perlu multiplexing
options.brightness = 80
options.gpio_slowdown = 4
matrix = RGBMatrix(options=options)

# Font
font = ImageFont.truetype(FONT_PATH, 26) if os.path.exists(FONT_PATH) else ImageFont.load_default()

# ==============================
# Fungsi Tampilan
# ==============================
def draw_text(text, color=(0, 255, 0)):
    image = Image.new("RGB", (W, H), (0, 0, 0))
    draw = ImageDraw.Draw(image)
    bbox = draw.textbbox((0, 0), text, font=font)
    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]
    x_text = (W - text_width) // 2 + 1
    y_text = (H - text_height) // 2 - 6
    draw.text((x_text, y_text), text, font=font, fill=color)
    return image

# ==============================
# Loop Utama
# ==============================
def speed_loop():
    global speed_limit
    last_config_check = 0
    config_interval = 30
    config = read_config()
    speed_limit = read_config().get("speed_limit", 50)
    record = config.get("record", 10)


    relay_on_until = 0
    current_speed = 0
    last_record_time = 0
   
    last_log_time = 0


    while True:
        # Baca data TSR20
        frame_data = ser.read(4)
        if len(frame_data) == 4:
            header = frame_data[0:2]
            speed = frame_data[2]
            terminator = frame_data[3]
            if terminator == 0x00:
                current_speed = speed

        # Reload config tiap 30 detik
        if time.time() - last_config_check > config_interval:
            try:
                cfg = read_config()
                new_limit = int(cfg.get("speed_limit", speed_limit))
                new_cooldown = int(cfg.get("record", record))
                if new_limit != speed_limit:
                    print(f"[INFO] Speed limit berubah: {speed_limit} -> {new_limit}")
                if new_cooldown != record:
                    print(f"[INFO] Cooldown berubah: {record} -> {new_cooldown}")
                speed_limit = new_limit
                record = new_cooldown
            except Exception as e:
                print(f"[WARN] Gagal baca config: {e}")
            last_config_check = time.time()


        # Print realtime
        print(f"Kecepatan: {current_speed} km/h", end="\r", flush=True)

        # Tentukan warna teks
        color = (255, 0, 0) if current_speed >= speed_limit else (0, 255, 0)
        
        # Tampilkan ke panel
        if current_speed != 0:
            frame = draw_text(str(current_speed), color=color)
            matrix.SetImage(frame)
            time.sleep(0.05)
        else:
            matrix.SetImage(Image.new("RGB", (W, H), (0, 0, 0)))

        # Rekam & log kalau over limit
        if current_speed >= speed_limit and (time.time() - last_record_time > record):
            start_recording()
            last_record_time = time.time()
            log_speed(current_speed, with_video=True)
            GPIO.setup(pinrelay, GPIO.OUT)
            GPIO.output(pinrelay, GPIO.LOW)
            relay_on_until = time.time() + record
        elif current_speed != 0 and (time.time() - last_log_time >= 1):
            log_speed(current_speed, with_video=False)
            last_log_time = time.time()

        # Matikan relay setelah timeout
        if relay_on_until > 0 and time.time() >= relay_on_until:
            GPIO.setup(pinrelay, GPIO.IN)
            print(f"[INFO] Rekaman Selesai ")
            relay_on_until = 0

# ==============================
# Main
# ==============================
if __name__ == '__main__':
    show_smile()          
    time.sleep(2)  
    Thread(target=speed_loop, daemon=True).start()
    app.run(host='0.0.0.0', port=5001, debug=False)


