import os
import base64
import shutil
import tempfile
from urllib.parse import quote
from flask import Flask, request, Response, jsonify
from yt_dlp import YoutubeDL

from dotenv import load_dotenv, find_dotenv
load_dotenv(find_dotenv())

app = Flask(__name__)

# On app startup, if COOKIES_BASE64 is set, write it out to /tmp/cookies.txt
b64 = os.environ.get('COOKIES_BASE64')
if b64:
    tmpdir_env = os.environ.get('TMPDIR', '/tmp')
    cookies_path = os.path.join(tmpdir_env, 'cookies.txt')
    with open(cookies_path, 'wb') as f:
        f.write(base64.b64decode(b64))
    print(f'Wrote cookies to {cookies_path}')
    # make cookie path available for downloads
    os.environ['YTDL_COOKIES_FILE'] = cookies_path

@app.route('/healthz', methods=['GET'])
def health_check():
    return jsonify({'status': 'ok'}), 200

@app.route('/download', methods=['GET', 'POST'])
def download_video():
    # Accept URL via query parameter or JSON body
    data = request.get_json(silent=True) or {}
    video_url = request.args.get('url') or data.get('url')
    if not video_url:
        return jsonify({'error': "Missing 'url' parameter"}), 400

    # Prepare temp directory in Render's ephemeral storage (/tmp)
    tmpdir = tempfile.mkdtemp(dir=os.environ.get('TMPDIR', '/tmp'))
    outtmpl = os.path.join(tmpdir, '%(id)s.%(ext)s')
    
    # Build yt-dlp options
    
    ydl_opts = {
        'format': 'bestvideo+bestaudio/best',
        'outtmpl': outtmpl,
        'merge_output_format': 'mp4',
        'quiet': False,
        'no_warnings': True,
        'noplaylist': True,
    }
    
    ydl_opts.update({
        'use_oauth':         True,
        'allow_oauth_cache': True,
        'oauth_client_id':     os.environ.get('YTDL_OAUTH_CLIENT_ID'),
        'oauth_client_secret': os.environ.get('YTDL_OAUTH_CLIENT_SECRET'),
    })

    # Attach cookies file if available
    cookiefile = os.environ.get('YTDL_COOKIES_FILE')
    if cookiefile and os.path.isfile(cookiefile):
        ydl_opts['cookiefile'] = cookiefile
        
    print(">>> YTDL is using cookie file:", ydl_opts.get('cookiefile'))

    try:
        # Download video
        with YoutubeDL(ydl_opts) as ydl:
            try:
                info = ydl.extract_info(video_url, download=True)
            except Exception as auth_err:
                # retry anonymously
                ydl_opts.pop('cookiefile', None)
                info = ydl.extract_info(video_url, download=True)


        # Determine final filename
        filepath = ydl.prepare_filename(info)
        if ydl_opts.get('merge_output_format'):
            base, _ = os.path.splitext(filepath)
            filepath = f"{base}.{ydl_opts['merge_output_format']}"

        # Stream file in chunks
        def generate():
            with open(filepath, 'rb') as f:
                for chunk in iter(lambda: f.read(8192), b""):
                    yield chunk
        
        # Build a safe download name (Unicode → percent-encoded)
        safe_title = info.get('title', info.get('id')).replace('"', '')
        download_name = f"{safe_title}.mp4"
        qname = quote(download_name)
        headers = {
            'Content-Disposition': f"attachment; filename*=UTF-8''{qname}"
        }
        response = Response(generate(), mimetype='video/mp4', headers=headers)
        # Cleanup after the response completes
        response.call_on_close(lambda: shutil.rmtree(tmpdir, ignore_errors=True))
        return response

    except Exception as e:
        shutil.rmtree(tmpdir, ignore_errors=True)
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, threaded=True)