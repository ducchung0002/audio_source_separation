import os
import subprocess
from flask import Flask, request, send_file, jsonify
from flask_cors import CORS
from werkzeug.utils import secure_filename
import sys
import logging
import time
import shutil
import threading
from gevent import monkey
from gevent.pywsgi import WSGIServer

monkey.patch_all()

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)  # Enable CORS for all routes and origins

# Define static folders
UPLOAD_FOLDER = os.path.join(app.root_path, 'static', 'uploads')
SEPARATED_FOLDER = os.path.join(app.root_path, 'static', 'separated')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(SEPARATED_FOLDER, exist_ok=True)

MODEL_NAME = 'hdemucs_mmi'

# Allowed audio extensions
ALLOWED_EXTENSIONS = {'mp3', 'wav', 'flac', 'm4a', 'aac', 'ogg'}


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def delayed_cleanup_task(output_dir, temp_file_path):
    def cleanup():
        time.sleep(600)
        try:
            logger.info("Cleanup thread started. Performing cleanup.")
            if os.path.exists(temp_file_path):
                os.remove(temp_file_path)
                logger.info(f"Deleted temporary file: {temp_file_path}")
            else:
                logger.warning(f"Temporary file not found: {temp_file_path}")
            if os.path.exists(output_dir):
                shutil.rmtree(output_dir)
                logger.info(f"Deleted output directory: {output_dir}")
            else:
                logger.warning(f"Output directory not found: {output_dir}")
        except Exception as e:
            logger.error(f"Error during cleanup: {e}")

    threading.Thread(target=cleanup, daemon=True).start()


@app.post('/separate')
def separate_vocals():
    if 'audio' not in request.files:
        return jsonify({"error": "No audio part in the request."}), 400

    audio = request.files['audio']

    if audio.filename == '':
        return jsonify({"error": "No file selected for uploading."}), 400

    if not allowed_file(audio.filename):
        return jsonify({"error": "Unsupported file type."}), 400

    try:
        # Secure the filename
        original_filename = secure_filename(audio.filename)
        filename_without_ext = os.path.splitext(original_filename)[0]

        # Path to save the uploaded audio file
        temp_file_path = os.path.join(UPLOAD_FOLDER, original_filename)
        audio.save(temp_file_path)

        # Path to the output directory
        output_dir = os.path.join(SEPARATED_FOLDER, os.urandom(8).hex())
        os.makedirs(output_dir, exist_ok=True)

        # Construct the Demucs command
        demucs_command = [
            sys.executable, '-m', 'demucs.separate',
            temp_file_path,
            f'--name={MODEL_NAME}',
            '--shifts=1',
            '--segment=45',
            '--two-stems=vocals',
            f'--out={output_dir}',
            '--verbose'
        ]

        # Run the Demucs separation process and print output
        subprocess.run(
            demucs_command,
            check=True
        )

        # Path to the output no_vocals.wav file
        output_file_path = os.path.join(
            output_dir,
            MODEL_NAME,
            filename_without_ext,
            'no_vocals.wav'
        )

        if not os.path.isfile(output_file_path):
            return jsonify({
                "error": "Output file not found after separation."
            }), 500

        # Send the output file to the client
        response = send_file(
            output_file_path,
            as_attachment=True,
            download_name=f'no_vocals_{original_filename}',
            mimetype='audio/wav'
        )

        # Start the cleanup in a separate thread
        delayed_cleanup_task(output_dir, temp_file_path)
        logger.info("Scheduled cleanup task.")

        return response

    except Exception as e:
        logger.error(f"Error sending file: {e}")
        return jsonify({
            "error": "Demucs separation failed.",
            "details": str(e)
        }), 500


if __name__ == '__main__':
    logger.info("Starting server on port 9999...")
    http_server = WSGIServer(('0.0.0.0', 9999), app)
    http_server.serve_forever()
