import os
import shutil
import tempfile
from flask import Flask, request, Response, jsonify
from yt_dlp import YoutubeDL

app = Flask(__name__)

@app.route('/healthz', methods=['GET'])
def health_check():
    return jsonify({'status': 'ok'}), 200

@app.route('/download', methods=['GET', 'POST'])
def download_video():
    # Accept URL via query parameter or JSON body
    video_url = request.args.get('url') or (request.json and request.json.get('url'))
    if not video_url:
        return jsonify({'error': "Missing 'url' parameter"}), 400

    # Create temp directory in Render's ephemeral storage (/tmp)
    tmpdir = tempfile.mkdtemp(dir=os.environ.get('TMPDIR', '/tmp'))
    outtmpl = os.path.join(tmpdir, '%(id)s.%(ext)s')
    ydl_opts = {
        'format': 'bestvideo+bestaudio/best',  # merge best video + audio
        'outtmpl': outtmpl,
        'merge_output_format': 'mp4',          # force mp4 container
        'quiet': True,
        'no_warnings': True,
        'noplaylist': True,
    }

    try:
        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(video_url, download=True)

        # Determine filename
        filename = ydl.prepare_filename(info)
        if ydl_opts.get('merge_output_format'):
            base, _ = os.path.splitext(filename)
            filename = f"{base}.{ydl_opts['merge_output_format']}"

        # Stream the file in chunks
        def generate():
            with open(filename, 'rb') as f:
                while True:
                    chunk = f.read(8192)
                    if not chunk:
                        break
                    yield chunk

        headers = {
            'Content-Disposition': f'attachment; filename="{info.get("title", info.get("id"))}.mp4"'
        }
        response = Response(generate(), mimetype='video/mp4', headers=headers)
        # Cleanup after response completes
        response.call_on_close(lambda: shutil.rmtree(tmpdir, ignore_errors=True))
        return response

    except Exception as e:
        shutil.rmtree(tmpdir, ignore_errors=True)
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, threaded=True)