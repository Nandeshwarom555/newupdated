import os
import logging
from flask import Flask, render_template_string, request, redirect, url_for, jsonify

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Create a Flask app
app = Flask(__name__)
app.secret_key = os.environ.get("SESSION_SECRET", "dev_secret_key")

@app.route('/health')
def health():
    """Health check endpoint for Koyeb."""
    return jsonify({"status": "ok"})

@app.route('/')
def index():
    """Home page route."""
    return render_template_string("""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Video Merger Bot</title>
        <link href="https://cdn.replit.com/agent/bootstrap-agent-dark-theme.min.css" rel="stylesheet">
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
    </head>
    <body class="bg-dark text-light">
        <div class="container py-5">
            <div class="row justify-content-center">
                <div class="col-md-8">
                    <div class="card bg-dark border-secondary">
                        <div class="card-header">
                            <h1 class="text-center">Video Merger Telegram Bot</h1>
                        </div>
                        <div class="card-body">
                            <p class="lead">This is a Telegram bot that downloads and merges videos from various sources.</p>
                            <p>To use the bot:</p>
                            <ol>
                                <li>Open Telegram and search for your bot</li>
                                <li>Start a conversation with the bot by clicking the Start button</li>
                                <li>Use the /merge command to begin adding video links</li>
                                <li>Send video URLs one by one or multiple URLs in one message</li>
                                <li>Press the Done button when finished adding videos</li>
                                <li>Wait for the bot to process and merge your videos (with progress updates)</li>
                                <li>Get a download link for your merged video from any file hosting service</li>
                            </ol>
                            <p class="mt-4">
                                <strong>Bot Status:</strong> 
                                <span class="badge bg-success">Running</span>
                            </p>
                            <div class="mt-4">
                                <h4>Supported Video Sources</h4>
                                <ul>
                                    <li>YouTube</li>
                                    <li>Vimeo</li>
                                    <li>Twitter/X</li>
                                    <li>Instagram</li>
                                    <li>Facebook</li>
                                    <li>Direct video links (.mp4, .webm, etc.)</li>
                                </ul>
                            </div>
                            <div class="mt-4">
                                <h4>Features</h4>
                                <ul>
                                    <li>Handles videos of any size (up to 10GB per video)</li>
                                    <li>Live progress tracking for all operations</li>
                                    <li>Uploads to multiple file hosting services with fallbacks</li>
                                    <li>Intelligent video format conversion</li>
                                    <li>Maintains video quality during processing</li>
                                    <li>Standardizes different video formats and dimensions</li>
                                </ul>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    </body>
    </html>
    """)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)