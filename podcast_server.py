import os
import re
import sys
import json
import urllib.parse
import http.server
import socketserver
import xml.etree.ElementTree as ET
from datetime import datetime
import email.utils

# Default Paths (relative to the Obsidian vault root)
PORT = 8085
VAULT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Attempt to load port from plugin settings
plugin_data_path = os.path.join(VAULT_DIR, ".obsidian", "plugins", "knowledge-pipeline", "data.json")
if os.path.exists(plugin_data_path):
    try:
        with open(plugin_data_path, "r", encoding="utf-8") as f:
            plugin_settings = json.load(f)
            PORT = int(plugin_settings.get("podcastServerPort", PORT))
    except Exception as e:
        pass

ATTACHMENTS_DIR = os.path.join(VAULT_DIR, "99_System", "Attachments")

def normalize_name(name):
    """Normalize string for name matching by removing space, lowercase, etc."""
    return re.sub(r'\s+', ' ', name.lower().replace("_", " ").replace("-", " ")).strip()

def parse_frontmatter(content):
    """Simple parser for frontmatter to avoid external yaml dependency."""
    metadata = {}
    lines = content.splitlines()
    if len(lines) > 1 and lines[0].strip() == '---':
        for i in range(1, len(lines)):
            if lines[i].strip() == '---':
                break
            line = lines[i]
            if ':' in line:
                key, val = line.split(':', 1)
                key = key.strip()
                val = val.strip().strip('"').strip("'")
                metadata[key] = val
    return metadata

def scan_notes_metadata(vault_path):
    """Scan all markdown files in the vault and build index for metadata matching."""
    embed_map = {}
    basename_map = {}
    
    # Walk the Obsidian vault directories
    for root, dirs, files in os.walk(vault_path):
        # Skip hidden or system directories to improve speed
        dirs[:] = [d for d in dirs if not d.startswith(".") and d not in ("venv", ".venv", "node_modules")]
        
        for file in files:
            if not file.endswith(".md"):
                continue
            
            note_path = os.path.join(root, file)
            rel_path = os.path.relpath(note_path, vault_path).replace("\\", "/")
            
            # Determine folder category
            category = "knowledge"
            if rel_path.startswith("00_Imports/") or rel_path.startswith("01_Inbox/"):
                category = "imports"
            elif rel_path.startswith("01_Incubator/"):
                category = "incubator"
            elif rel_path.startswith("03_Knowledge/"):
                category = "knowledge"
            elif rel_path.startswith("99_Archive/"):
                category = "archive"
            
            # Read content to parse metadata
            try:
                with open(note_path, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()
            except Exception:
                continue
                
            metadata = parse_frontmatter(content)
            note_title = os.path.splitext(file)[0]
            
            note_info = {
                'title': note_title,
                'path': note_path,
                'rel_path': rel_path,
                'category': category,
                'topic': metadata.get('topic') or metadata.get('triage_topic') or 'General',
                'summary': metadata.get('summarization') or metadata.get('summary') or metadata.get('triage_summary') or 'No description available.',
                'url': metadata.get('url') or ''
            }
            
            # Index by normalized base name
            norm_title = normalize_name(note_title)
            basename_map[norm_title] = note_info
            
            # Index by any embedded audio files inside the note
            # Matches ![[File Name Podcast.mp3]] or similar
            embeds = re.findall(r'!\[\[(.*?\.mp3)\]\]', content)
            for emb in embeds:
                embed_map[emb] = note_info
                # Also index clean filename without extension
                clean_emb = os.path.splitext(emb)[0]
                embed_map[clean_emb] = note_info

    return embed_map, basename_map

def get_podcast_list():
    """Scan attachments for *Podcast.mp3 files and match metadata from markdown notes."""
    embed_map, basename_map = scan_notes_metadata(VAULT_DIR)
    podcasts = []
    
    if not os.path.exists(ATTACHMENTS_DIR):
        return podcasts
        
    for item in os.listdir(ATTACHMENTS_DIR):
        if not item.endswith("Podcast.mp3") and not (item.endswith(".mp3") and "podcast" in item.lower()):
            continue
            
        file_path = os.path.join(ATTACHMENTS_DIR, item)
        if not os.path.isfile(file_path):
            continue
            
        # Get basic file details
        stat = os.stat(file_path)
        size = stat.st_size
        mtime = stat.st_mtime
        
        # Clean title from filename
        # e.g., "Universal Cell Embedding ... Podcast.mp3" -> "Universal Cell Embedding ..."
        clean_base = re.sub(r'Podcast(\s*\(\d+\))?\.mp3$', '', item, flags=re.IGNORECASE).strip()
        clean_base = re.sub(r'\s*\(\d+\)$', '', clean_base).strip()
        
        # Attempt matching to note metadata
        matched_note = None
        
        # 1. Match by exact attachment filename embed
        if item in embed_map:
            matched_note = embed_map[item]
        elif clean_base in embed_map:
            matched_note = embed_map[clean_base]
            
        # 2. Match by normalized name
        if not matched_note:
            norm_clean = normalize_name(clean_base)
            if norm_clean in basename_map:
                matched_note = basename_map[norm_clean]
            else:
                # Substring matching
                for norm_title, info in basename_map.items():
                    if len(norm_title) >= 12 and (norm_title in norm_clean or norm_clean in norm_title):
                        matched_note = info
                        break
                        
        # 3. Match by domain words (e.g. Source MIT News https...)
        if not matched_note:
            domain_match = re.search(r'Source\s+(.*?)\s+https', clean_base, re.IGNORECASE)
            if domain_match:
                domain_str = domain_match.group(1)
                words = [w.lower() for w in re.sub(r'[^a-zA-Z0-9\s]', '', domain_str).split() if len(w) > 2]
                if words:
                    for norm_title, info in basename_map.items():
                        note_url = info['url'].lower()
                        note_title_lower = info['title'].lower()
                        if any(word in note_url or word in note_title_lower for word in words):
                            matched_note = info
                            break
                            
        # Consolidate attributes
        if matched_note:
            title = matched_note['title']
            summary = matched_note['summary']
            topic = matched_note['topic']
            category = matched_note['category']
            url = matched_note['url']
        else:
            title = clean_base
            summary = "No Obsidian notes matched. Served from attachments queue."
            topic = "Uncategorized"
            category = "archive"
            url = ""
            
        podcasts.append({
            'filename': item,
            'title': title,
            'summary': summary,
            'topic': topic,
            'category': category,
            'url': url,
            'size': size,
            'mtime': mtime
        })
        
    # Sort by modification time desc (newest first)
    podcasts.sort(key=lambda x: x['mtime'], reverse=True)
    return podcasts

class PodcastHTTPHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        # Override to log cleanly
        sys.stderr.write("%s - - [%s] %s\n" %
                         (self.address_string(),
                          self.log_date_time_string(),
                          format%args))

    def do_GET(self):
        # Parse path
        parsed_url = urllib.parse.urlparse(self.path)
        path = parsed_url.path
        
        # 1. API: List Podcasts
        if path == '/api/podcasts':
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            try:
                podcasts = get_podcast_list()
                self.wfile.write(json.dumps(podcasts).encode('utf-8'))
            except Exception as e:
                self.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))
            return
            
        # 2. RSS Feed: feed.xml
        if path in ('/feed.xml', '/rss', '/feed'):
            self.serve_rss_feed()
            return
            
        # 3. Audio Streaming (with HTTP 206 Range Request support)
        if path.startswith('/audio/'):
            filename = urllib.parse.unquote(path[7:])
            filepath = os.path.join(ATTACHMENTS_DIR, filename)
            if not os.path.exists(filepath) or not os.path.isfile(filepath):
                self.send_error(404, "File Not Found")
                return
            self.serve_audio_file(filepath)
            return
            
        # 4. Web App UI (index.html)
        if path in ('/', '/index.html'):
            self.serve_web_app()
            return
            
        self.send_error(404, "Not Found")

    def serve_audio_file(self, filepath):
        file_size = os.path.getsize(filepath)
        range_header = self.headers.get('Range')
        
        if not range_header:
            self.send_response(200)
            self.send_header('Content-Type', 'audio/mpeg')
            self.send_header('Content-Length', str(file_size))
            self.send_header('Accept-Ranges', 'bytes')
            self.end_headers()
            with open(filepath, 'rb') as f:
                self.wfile.write(f.read())
            return
            
        # Parse Range: bytes=start-end
        match = re.match(r'bytes=(\d*)-(\d*)', range_header)
        if not match:
            self.send_error(400, "Bad Request: Invalid Range")
            self.wfile.write(b"Invalid Range Header")
            return
            
        start_str, end_str = match.groups()
        start = int(start_str) if start_str else 0
        end = int(end_str) if end_str else file_size - 1
        
        if start >= file_size:
            self.send_response(416)
            self.send_header('Content-Range', f'bytes */{file_size}')
            self.end_headers()
            return
            
        if end >= file_size:
            end = file_size - 1
            
        chunk_size = end - start + 1
        self.send_response(206)
        self.send_header('Content-Type', 'audio/mpeg')
        self.send_header('Content-Range', f'bytes {start}-{end}/{file_size}')
        self.send_header('Content-Length', str(chunk_size))
        self.send_header('Accept-Ranges', 'bytes')
        self.end_headers()
        
        with open(filepath, 'rb') as f:
            f.seek(start)
            remaining = chunk_size
            buffer_size = 128 * 1024
            while remaining > 0:
                chunk = f.read(min(buffer_size, remaining))
                if not chunk:
                    break
                self.wfile.write(chunk)
                remaining -= len(chunk)

    def serve_rss_feed(self):
        host = self.headers.get('Host', f'localhost:{PORT}')
        podcasts = get_podcast_list()
        
        # Build RSS XML
        rss = ET.Element('rss', {
            'version': '2.0',
            'xmlns:itunes': 'http://www.itunes.com/dtds/podcast-1.0.dtd',
            'xmlns:content': 'http://purl.org/rss/1.0/modules/content/'
        })
        channel = ET.SubElement(rss, 'channel')
        
        ET.SubElement(channel, 'title').text = "Obsidian NotebookLM Podcasts"
        ET.SubElement(channel, 'link').text = f"http://{host}/"
        ET.SubElement(channel, 'description').text = "NotebookLM articles podcasts streamed over your tailnet."
        ET.SubElement(channel, 'language').text = "en-us"
        
        # Channel category & cover
        ET.SubElement(channel, 'itunes:category', {'text': 'Education'})
        
        for item in podcasts:
            item_el = ET.SubElement(channel, 'item')
            ET.SubElement(item_el, 'title').text = item['title']
            ET.SubElement(item_el, 'description').text = f"{item['topic']} | {item['summary']}"
            
            pub_date = email.utils.formatdate(item['mtime'], usegmt=True)
            ET.SubElement(item_el, 'pubDate').text = pub_date
            
            # Enclosure points dynamically to current host (works over tailnet and localhost!)
            enc_url = f"http://{host}/audio/{urllib.parse.quote(item['filename'])}"
            ET.SubElement(item_el, 'enclosure', {
                'url': enc_url,
                'length': str(item['size']),
                'type': 'audio/mpeg'
            })
            ET.SubElement(item_el, 'guid', {'isPermaLink': 'false'}).text = item['filename']
            ET.SubElement(item_el, 'itunes:summary').text = item['summary']
            
        xml_bytes = b'<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(rss, encoding='utf-8')
        
        self.send_response(200)
        self.send_header('Content-Type', 'application/rss+xml; charset=utf-8')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(xml_bytes)

    def serve_web_app(self):
        html_content = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Podcast Vault</title>
    <!-- Outfit Font -->
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;500;600;700&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg-gradient: radial-gradient(circle at top right, #1e1b4b, #0f172a 60%);
            --panel-bg: rgba(30, 41, 59, 0.45);
            --panel-border: rgba(255, 255, 255, 0.08);
            --panel-hover: rgba(255, 255, 255, 0.12);
            --accent-primary: #8b5cf6;
            --accent-secondary: #6366f1;
            --accent-glow: rgba(139, 92, 246, 0.35);
            --text-primary: #f8fafc;
            --text-secondary: #94a3b8;
            --text-muted: #64748b;
            --success: #10b981;
            --font-family: 'Outfit', -apple-system, BlinkMacSystemFont, sans-serif;
        }

        * {
            box-sizing: border-box;
            margin: 0;
            padding: 0;
        }

        body {
            font-family: var(--font-family);
            background: var(--bg-gradient);
            background-attachment: fixed;
            color: var(--text-primary);
            min-height: 100vh;
            display: flex;
            flex-direction: column;
            padding: 20px;
            padding-bottom: 140px; /* Space for the bottom player */
        }

        header {
            max-width: 1200px;
            width: 100%;
            margin: 0 auto 30px auto;
            display: flex;
            flex-direction: column;
            gap: 20px;
        }

        .header-top {
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-wrap: wrap;
            gap: 15px;
        }

        .logo-section {
            display: flex;
            align-items: center;
            gap: 12px;
        }

        .logo-icon {
            background: linear-gradient(135deg, var(--accent-primary), var(--accent-secondary));
            width: 45px;
            height: 45px;
            border-radius: 12px;
            display: flex;
            align-items: center;
            justify-content: center;
            box-shadow: 0 0 20px var(--accent-glow);
        }

        .logo-icon svg {
            width: 24px;
            height: 24px;
            fill: white;
        }

        h1 {
            font-size: 1.8rem;
            font-weight: 700;
            letter-spacing: -0.02em;
            background: linear-gradient(135deg, #fff, var(--text-secondary));
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }

        .rss-btn {
            display: inline-flex;
            align-items: center;
            gap: 8px;
            padding: 10px 16px;
            border-radius: 10px;
            background: var(--panel-bg);
            border: 1px solid var(--panel-border);
            color: #f97316; /* RSS Orange */
            font-weight: 500;
            font-size: 0.95rem;
            text-decoration: none;
            cursor: pointer;
            transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
        }

        .rss-btn:hover {
            background: rgba(249, 115, 22, 0.15);
            border-color: #f97316;
            transform: translateY(-2px);
        }

        .rss-btn svg {
            width: 18px;
            height: 18px;
            fill: currentColor;
        }

        /* Search & Filters */
        .controls-section {
            display: flex;
            flex-direction: column;
            gap: 15px;
            width: 100%;
        }

        .search-container {
            position: relative;
            width: 100%;
        }

        .search-input {
            width: 100%;
            padding: 14px 20px 14px 50px;
            border-radius: 14px;
            background: var(--panel-bg);
            border: 1px solid var(--panel-border);
            color: var(--text-primary);
            font-size: 1rem;
            font-family: var(--font-family);
            outline: none;
            transition: all 0.3s;
        }

        .search-input:focus {
            border-color: var(--accent-primary);
            box-shadow: 0 0 15px var(--accent-glow);
            background: rgba(30, 41, 59, 0.7);
        }

        .search-icon {
            position: absolute;
            left: 18px;
            top: 50%;
            transform: translateY(-50%);
            width: 20px;
            height: 20px;
            fill: var(--text-secondary);
            pointer-events: none;
        }

        .tabs-container {
            display: flex;
            gap: 8px;
            overflow-x: auto;
            padding-bottom: 5px;
            scrollbar-width: none;
        }

        .tabs-container::-webkit-scrollbar {
            display: none;
        }

        .tab-btn {
            padding: 8px 18px;
            border-radius: 20px;
            background: var(--panel-bg);
            border: 1px solid var(--panel-border);
            color: var(--text-secondary);
            font-size: 0.9rem;
            font-weight: 500;
            cursor: pointer;
            white-space: nowrap;
            transition: all 0.2s;
        }

        .tab-btn:hover {
            color: var(--text-primary);
            background: var(--panel-hover);
        }

        .tab-btn.active {
            background: linear-gradient(135deg, var(--accent-primary), var(--accent-secondary));
            border-color: transparent;
            color: white;
            box-shadow: 0 4px 15px var(--accent-glow);
        }

        /* Podcast List Grid */
        main {
            max-width: 1200px;
            width: 100%;
            margin: 0 auto;
            flex: 1;
        }

        .podcast-grid {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(340px, 1fr));
            gap: 20px;
        }

        .podcast-card {
            background: var(--panel-bg);
            backdrop-filter: blur(16px);
            border: 1px solid var(--panel-border);
            border-radius: 16px;
            padding: 20px;
            display: flex;
            flex-direction: column;
            gap: 15px;
            position: relative;
            overflow: hidden;
            transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
        }

        .podcast-card::before {
            content: '';
            position: absolute;
            top: 0;
            left: 0;
            right: 0;
            height: 4px;
            background: linear-gradient(90deg, var(--accent-primary), var(--accent-secondary));
            opacity: 0;
            transition: opacity 0.3s;
        }

        .podcast-card:hover {
            transform: translateY(-5px);
            border-color: rgba(255, 255, 255, 0.15);
            box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.4);
        }

        .podcast-card:hover::before {
            opacity: 1;
        }

        .podcast-card.playing {
            border-color: var(--accent-primary);
            box-shadow: 0 0 20px rgba(139, 92, 246, 0.15);
        }

        .podcast-card.playing::before {
            opacity: 1;
        }

        .card-header {
            display: flex;
            justify-content: space-between;
            align-items: flex-start;
            gap: 10px;
        }

        .topic-badge {
            font-size: 0.75rem;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            padding: 4px 8px;
            border-radius: 6px;
            background: rgba(139, 92, 246, 0.12);
            color: #c084fc;
            max-width: 75%;
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
        }

        .category-tag {
            font-size: 0.75rem;
            font-weight: 500;
            color: var(--text-muted);
            background: rgba(255, 255, 255, 0.04);
            padding: 4px 8px;
            border-radius: 6px;
            text-transform: capitalize;
        }

        .card-title {
            font-size: 1.15rem;
            font-weight: 600;
            line-height: 1.4;
            color: var(--text-primary);
            display: -webkit-box;
            -webkit-line-clamp: 2;
            -webkit-box-orient: vertical;
            overflow: hidden;
        }

        .card-summary {
            font-size: 0.9rem;
            line-height: 1.5;
            color: var(--text-secondary);
            display: -webkit-box;
            -webkit-line-clamp: 3;
            -webkit-box-orient: vertical;
            overflow: hidden;
            transition: max-height 0.3s;
        }

        .card-summary.expanded {
            display: block;
            overflow: visible;
            -webkit-line-clamp: unset;
        }

        .read-more-btn {
            background: none;
            border: none;
            color: var(--accent-primary);
            font-size: 0.85rem;
            font-weight: 500;
            cursor: pointer;
            align-self: flex-start;
            margin-top: -8px;
            display: flex;
            align-items: center;
            gap: 4px;
        }

        .read-more-btn:hover {
            color: #a78bfa;
            text-decoration: underline;
        }

        .card-footer {
            margin-top: auto;
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding-top: 15px;
            border-top: 1px solid rgba(255, 255, 255, 0.04);
        }

        .meta-info {
            display: flex;
            flex-direction: column;
            gap: 4px;
            font-size: 0.8rem;
            color: var(--text-muted);
        }

        .play-card-btn {
            background: linear-gradient(135deg, var(--accent-primary), var(--accent-secondary));
            border: none;
            width: 42px;
            height: 42px;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            cursor: pointer;
            box-shadow: 0 4px 10px rgba(0, 0, 0, 0.3);
            transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
        }

        .play-card-btn:hover {
            transform: scale(1.1);
            box-shadow: 0 0 15px var(--accent-glow);
        }

        .play-card-btn svg {
            width: 18px;
            height: 18px;
            fill: white;
            transition: transform 0.1s;
        }

        /* Empty State */
        .empty-state {
            text-align: center;
            padding: 80px 20px;
            background: var(--panel-bg);
            border: 1px dashed var(--panel-border);
            border-radius: 16px;
            max-width: 500px;
            margin: 40px auto;
        }

        .empty-state svg {
            width: 48px;
            height: 48px;
            fill: var(--text-muted);
            margin-bottom: 16px;
        }

        .empty-state h3 {
            font-size: 1.25rem;
            margin-bottom: 8px;
        }

        .empty-state p {
            color: var(--text-secondary);
            font-size: 0.95rem;
        }

        /* Persistent Bottom Player Bar */
        .player-bar {
            position: fixed;
            bottom: 0;
            left: 0;
            right: 0;
            background: rgba(15, 23, 42, 0.8);
            backdrop-filter: blur(20px);
            border-top: 1px solid var(--panel-border);
            padding: 16px 24px;
            z-index: 1000;
            box-shadow: 0 -10px 30px rgba(0, 0, 0, 0.5);
            display: none;
            animation: slideUp 0.4s cubic-bezier(0.16, 1, 0.3, 1);
        }

        @keyframes slideUp {
            from { transform: translateY(100%); }
            to { transform: translateY(0); }
        }

        .player-container {
            max-width: 1200px;
            margin: 0 auto;
            display: grid;
            grid-template-columns: 280px 1fr 220px;
            align-items: center;
            gap: 20px;
        }

        /* Left Side: Track Info */
        .player-info {
            display: flex;
            flex-direction: column;
            gap: 4px;
            min-width: 0;
        }

        .player-title {
            font-size: 0.95rem;
            font-weight: 600;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
            color: var(--text-primary);
        }

        .player-meta {
            display: flex;
            align-items: center;
            gap: 8px;
            font-size: 0.8rem;
        }

        .player-topic {
            color: #c084fc;
            font-weight: 500;
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
        }

        .player-source-link {
            color: var(--text-muted);
            text-decoration: none;
            display: flex;
            align-items: center;
            gap: 3px;
        }

        .player-source-link:hover {
            color: var(--accent-primary);
            text-decoration: underline;
        }

        .player-source-link svg {
            width: 12px;
            height: 12px;
            fill: currentColor;
        }

        /* Center Side: Core Controls */
        .player-controls {
            display: flex;
            flex-direction: column;
            align-items: center;
            gap: 8px;
        }

        .buttons-row {
            display: flex;
            align-items: center;
            gap: 20px;
        }

        .control-btn {
            background: none;
            border: none;
            color: var(--text-secondary);
            cursor: pointer;
            display: flex;
            align-items: center;
            justify-content: center;
            transition: color 0.2s;
        }

        .control-btn:hover {
            color: var(--text-primary);
        }

        .control-btn svg {
            width: 22px;
            height: 22px;
            fill: currentColor;
        }

        .control-btn.play-pause-btn {
            background: white;
            color: #0f172a;
            width: 44px;
            height: 44px;
            border-radius: 50%;
            box-shadow: 0 4px 10px rgba(139, 92, 246, 0.2);
            transition: all 0.2s;
        }

        .control-btn.play-pause-btn:hover {
            transform: scale(1.05);
            background: #f1f5f9;
        }

        .control-btn.play-pause-btn svg {
            width: 20px;
            height: 20px;
            fill: currentColor;
        }

        /* Scrub Slider Row */
        .slider-row {
            width: 100%;
            display: flex;
            align-items: center;
            gap: 12px;
            font-size: 0.8rem;
            color: var(--text-secondary);
            font-variant-numeric: tabular-nums;
        }

        .progress-container {
            flex-grow: 1;
            position: relative;
            display: flex;
            align-items: center;
            height: 14px;
            cursor: pointer;
        }

        .progress-bar {
            width: 100%;
            height: 4px;
            border-radius: 2px;
            background: rgba(255, 255, 255, 0.1);
            position: relative;
        }

        .progress-filled {
            height: 100%;
            border-radius: 2px;
            background: linear-gradient(90deg, var(--accent-primary), var(--accent-secondary));
            width: 0%;
            position: absolute;
            left: 0;
            top: 0;
        }

        .progress-handle {
            width: 12px;
            height: 12px;
            border-radius: 50%;
            background: white;
            position: absolute;
            left: 0%;
            top: 50%;
            transform: translate(-50%, -50%);
            opacity: 0;
            transition: opacity 0.1s;
            box-shadow: 0 0 10px rgba(0, 0, 0, 0.5);
        }

        .progress-container:hover .progress-handle {
            opacity: 1;
        }

        .progress-container:hover .progress-bar {
            height: 6px;
        }

        /* Right Side: Speed & Volume */
        .player-settings {
            display: flex;
            align-items: center;
            justify-content: flex-end;
            gap: 15px;
        }

        .speed-control {
            position: relative;
        }

        .speed-btn {
            background: var(--panel-bg);
            border: 1px solid var(--panel-border);
            color: var(--text-secondary);
            padding: 6px 12px;
            border-radius: 8px;
            font-size: 0.85rem;
            font-weight: 500;
            cursor: pointer;
            font-family: var(--font-family);
            transition: all 0.2s;
        }

        .speed-btn:hover {
            color: var(--text-primary);
            border-color: rgba(255, 255, 255, 0.15);
        }

        .speed-menu {
            position: absolute;
            bottom: 45px;
            right: 0;
            background: #1e293b;
            border: 1px solid var(--panel-border);
            border-radius: 8px;
            padding: 6px 0;
            display: none;
            flex-direction: column;
            box-shadow: 0 4px 20px rgba(0, 0, 0, 0.4);
            z-index: 1001;
            min-width: 80px;
        }

        .speed-menu.show {
            display: flex;
        }

        .speed-option {
            background: none;
            border: none;
            color: var(--text-secondary);
            padding: 6px 16px;
            font-size: 0.85rem;
            cursor: pointer;
            text-align: left;
            font-family: var(--font-family);
            width: 100%;
        }

        .speed-option:hover {
            background: rgba(255, 255, 255, 0.05);
            color: var(--text-primary);
        }

        .speed-option.active {
            color: var(--accent-primary);
            font-weight: 600;
        }

        .volume-control {
            display: flex;
            align-items: center;
            gap: 8px;
            color: var(--text-secondary);
        }

        .volume-control svg {
            width: 18px;
            height: 18px;
            fill: currentColor;
            cursor: pointer;
        }

        .volume-control svg:hover {
            color: var(--text-primary);
        }

        .volume-slider {
            width: 70px;
            height: 4px;
            -webkit-appearance: none;
            background: rgba(255, 255, 255, 0.15);
            border-radius: 2px;
            outline: none;
            cursor: pointer;
        }

        .volume-slider::-webkit-slider-thumb {
            -webkit-appearance: none;
            width: 10px;
            height: 10px;
            border-radius: 50%;
            background: white;
            cursor: pointer;
            box-shadow: 0 0 5px rgba(0,0,0,0.5);
        }

        /* Responsive Design */
        @media (max-width: 860px) {
            .player-container {
                grid-template-columns: 1fr;
                gap: 15px;
            }

            .player-info {
                align-items: center;
                text-align: center;
            }

            .player-settings {
                justify-content: center;
                width: 100%;
            }
            
            body {
                padding-bottom: 220px;
            }
        }
    </style>
</head>
<body>

    <header>
        <div class="header-top">
            <div class="logo-section">
                <div class="logo-icon">
                    <svg viewBox="0 0 24 24">
                        <path d="M12 2C6.48 2 2 6.48 2 12v5c0 .83.67 1.5 1.5 1.5h3c.83 0 1.5-.67 1.5-1.5v-4c0-.83-.67-1.5-1.5-1.5H4v-1c0-4.41 3.59-8 8-8s8 3.59 8 8v1h-2.5c-.83 0-1.5.67-1.5 1.5v4c0 .83.67 1.5 1.5 1.5h3c.83 0 1.5-.67 1.5-1.5v-5c0-5.52-4.48-10-10-10z"/>
                    </svg>
                </div>
                <h1>Podcast Vault</h1>
            </div>
            
            <a href="/feed.xml" class="rss-btn" target="_blank" title="Subscribe with your favorite podcast app!">
                <svg viewBox="0 0 24 24">
                    <path d="M6.18 15.64a2.18 2.18 0 1 1-4.36 0 2.18 2.18 0 0 1 4.36 0zM2 9.59c4.95 0 8.97 4.02 8.97 8.97h2.89C13.86 11.96 8.04 6.14 2 6.14v3.45zm0-5.85c7.98 0 14.47 6.49 14.47 14.47h2.9C19.37 8.39 11.61.63 2 .63v3.11z"/>
                </svg>
                Podcast RSS Feed
            </a>
        </div>

        <div class="controls-section">
            <div class="search-container">
                <svg class="search-icon" viewBox="0 0 24 24">
                    <path d="M15.5 14h-.79l-.28-.27C15.41 12.59 16 11.11 16 9.5 16 5.91 13.09 3 9.5 3S3 5.91 3 9.5 5.91 16 9.5 16c1.61 0 3.09-.59 4.23-1.57l.27.28v.79l5 4.99L20.49 19l-4.99-5zm-6 0C7.01 14 5 11.99 5 9.5S7.01 5 9.5 5 14 7.01 14 9.5 11.99 14 9.5 14z"/>
                </svg>
                <input type="text" id="search" class="search-input" placeholder="Search podcast title, topic, or summary...">
            </div>

            <div class="tabs-container" id="filter-tabs">
                <button class="tab-btn active" data-filter="all">All Episodes</button>
                <button class="tab-btn" data-filter="imports">Imports</button>
                <button class="tab-btn" data-filter="incubator">Incubator</button>
                <button class="tab-btn" data-filter="knowledge">Knowledge</button>
                <button class="tab-btn" data-filter="archive">Archive</button>
            </div>
        </div>
    </header>

    <main>
        <div class="podcast-grid" id="podcast-grid">
            <!-- Rendered dynamically -->
        </div>

        <div class="empty-state" id="empty-state" style="display: none;">
            <svg viewBox="0 0 24 24">
                <path d="M12 2C6.47 2 2 6.47 2 12s4.47 10 10 10 10-4.47 10-10S17.53 2 12 2zm1 15h-2v-6h2v6zm0-8h-2V7h2v2z"/>
            </svg>
            <h3>No podcasts found</h3>
            <p>Try searching for a different keyword or checking other filter tabs.</p>
        </div>
    </main>

    <!-- Bottom Player Bar -->
    <div class="player-bar" id="player-bar">
        <div class="player-container">
            <!-- Track Details -->
            <div class="player-info">
                <div class="player-title" id="player-title">Podcast Episode Title</div>
                <div class="player-meta">
                    <span class="player-topic" id="player-topic">Computational Biology</span>
                    <a href="#" class="player-source-link" id="player-source-link" target="_blank" style="display: none;">
                        <svg viewBox="0 0 24 24"><path d="M3.9 12c0-1.71 1.39-3.1 3.1-3.1h4V7H7c-2.76 0-5 2.24-5 5s2.24 5 5 5h4v-1.9H7c-1.71 0-3.1-1.39-3.1-3.1zM8 13h8v-2H8v2zm9-6h-4v1.9h4c1.71 0 3.1 1.39 3.1 3.1s-1.39 3.1-3.1 3.1h-4V17h4c2.76 0 5-2.24 5-5s-2.24-5-5-5z"/></svg>
                        Source Article
                    </a>
                </div>
            </div>

            <!-- Controls & Timeline -->
            <div class="player-controls">
                <div class="buttons-row">
                    <button class="control-btn" id="btn-back" title="Backward 15s">
                        <svg viewBox="0 0 24 24"><path d="M12 5V1L7 6l5 5V7c3.31 0 6 2.69 6 6s-2.69 6-6 6-6-2.69-6-6H4c0 4.42 3.58 8 8 8s8-3.58 8-8-3.58-8-8-8zm-1.33 9.47h-.96v-2.3h-.03l-.71.51-.23-.42 1.04-.7h.89v2.91zm2.34-1.35c0 .38-.05.7-.16.95a1.05 1.05 0 0 1-.46.46 1.7 1.7 0 0 1-.72.15c-.29 0-.53-.05-.72-.15a.99.99 0 0 1-.45-.45c-.11-.25-.16-.57-.16-.96v-.32c0-.39.05-.71.16-.97a1 1 0 0 1 .46-.46 1.74 1.74 0 0 1 .73-.15c.29 0 .53.05.73.15.2.1.35.25.46.47a1.44 1.44 0 0 1 .16.96v.31zm-.91-.45c0-.28-.02-.48-.07-.6-.05-.12-.13-.18-.24-.18-.11 0-.19.06-.24.18s-.07.33-.07.6v.56c0 .28.02.48.07.6s.13.18.24.18c.12 0 .2-.06.24-.18s.07-.32.07-.6v-.56z"/></svg>
                    </button>
                    
                    <button class="control-btn play-pause-btn" id="btn-play" title="Play">
                        <svg viewBox="0 0 24 24" id="play-icon"><path d="M8 5v14l11-7z"/></svg>
                        <svg viewBox="0 0 24 24" id="pause-icon" style="display: none;"><path d="M6 19h4V5H6v14zm8-14v14h4V5h-4z"/></svg>
                    </button>
                    
                    <button class="control-btn" id="btn-forward" title="Forward 15s">
                        <svg viewBox="0 0 24 24"><path d="M12 5v4c4.42 0 8 3.58 8 8s-3.58 8-8 8-8-3.58-8-8h2c0 3.31 2.69 6 6 6s6-2.69 6-6-2.69-6-6-6v4l5-5-5-5zm-1.33 9.47h-.96v-2.3h-.03l-.71.51-.23-.42 1.04-.7h.89v2.91zm2.34-1.35c0 .38-.05.7-.16.95a1.05 1.05 0 0 1-.46.46 1.7 1.7 0 0 1-.72.15c-.29 0-.53-.05-.72-.15a.99.99 0 0 1-.45-.45c-.11-.25-.16-.57-.16-.96v-.32c0-.39.05-.71.16-.97a1 1 0 0 1 .46-.46 1.74 1.74 0 0 1 .73-.15c.29 0 .53.05.73.15.2.1.35.25.46.47a1.44 1.44 0 0 1 .16.96v.31zm-.91-.45c0-.28-.02-.48-.07-.6-.05-.12-.13-.18-.24-.18-.11 0-.19.06-.24.18s-.07.33-.07.6v.56c0 .28.02.48.07.6s.13.18.24.18c.12 0 .2-.06.24-.18s.07-.32.07-.6v-.56z"/></svg>
                    </button>
                </div>

                <div class="slider-row">
                    <span id="current-time">0:00</span>
                    <div class="progress-container" id="progress-container">
                        <div class="progress-bar">
                            <div class="progress-filled" id="progress-filled"></div>
                            <div class="progress-handle" id="progress-handle"></div>
                        </div>
                    </div>
                    <span id="duration-time">0:00</span>
                </div>
            </div>

            <!-- Volume & Speed -->
            <div class="player-settings">
                <div class="speed-control">
                    <button class="speed-btn" id="speed-btn">1.0x</button>
                    <div class="speed-menu" id="speed-menu">
                        <button class="speed-option" data-speed="0.5">0.5x</button>
                        <button class="speed-option" data-speed="0.8">0.8x</button>
                        <button class="speed-option active" data-speed="1.0">1.0x</button>
                        <button class="speed-option" data-speed="1.25">1.25x</button>
                        <button class="speed-option" data-speed="1.5">1.5x</button>
                        <button class="speed-option" data-speed="1.75">1.75x</button>
                        <button class="speed-option" data-speed="2.0">2.0x</button>
                        <button class="speed-option" data-speed="2.5">2.5x</button>
                    </div>
                </div>

                <div class="volume-control">
                    <svg viewBox="0 0 24 24" id="volume-icon">
                        <path d="M3 9v6h4l5 5V4L7 9H3zm13.5 3c0-1.77-1.02-3.29-2.5-4.03v8.05c1.48-.73 2.5-2.25 2.5-4.02zM14 3.23v2.06c2.89.86 5 3.54 5 6.71s-2.11 5.85-5 6.71v2.06c4.01-.91 7-4.49 7-8.77s-2.99-7.86-7-8.77z"/>
                    </svg>
                    <input type="range" class="volume-slider" id="volume-slider" min="0" max="1" step="0.05" value="1">
                </div>
            </div>
        </div>
    </div>

    <script>
        let allPodcasts = [];
        let activeFilter = 'all';
        let searchQuery = '';
        
        // Audio Player State
        const audio = new Audio();
        let currentPodcast = null;
        let isSeeking = false;
        
        // DOM Elements
        const grid = document.getElementById('podcast-grid');
        const emptyState = document.getElementById('empty-state');
        const searchInput = document.getElementById('search');
        const filterTabs = document.getElementById('filter-tabs');
        
        const playerBar = document.getElementById('player-bar');
        const playerTitle = document.getElementById('player-title');
        const playerTopic = document.getElementById('player-topic');
        const playerSourceLink = document.getElementById('player-source-link');
        
        const btnPlay = document.getElementById('btn-play');
        const playIcon = document.getElementById('play-icon');
        const pauseIcon = document.getElementById('pause-icon');
        const btnBack = document.getElementById('btn-back');
        const btnForward = document.getElementById('btn-forward');
        
        const progressContainer = document.getElementById('progress-container');
        const progressFilled = document.getElementById('progress-filled');
        const progressHandle = document.getElementById('progress-handle');
        const currentTimeEl = document.getElementById('current-time');
        const durationTimeEl = document.getElementById('duration-time');
        
        const speedBtn = document.getElementById('speed-btn');
        const speedMenu = document.getElementById('speed-menu');
        const volumeIcon = document.getElementById('volume-icon');
        const volumeSlider = document.getElementById('volume-slider');

        // Format times helper
        function formatTime(secs) {
            if (isNaN(secs)) return "0:00";
            const m = Math.floor(secs / 60);
            const s = Math.floor(secs % 60);
            return `${m}:${s < 10 ? '0' : ''}${s}`;
        }

        // Fetch Podcasts
        async function fetchPodcasts() {
            try {
                const res = await fetch('/api/podcasts');
                allPodcasts = await res.json();
                renderPodcasts();
            } catch (err) {
                console.error("Failed to load podcasts", err);
                grid.innerHTML = `<div class="empty-state"><h3>Error loading podcasts</h3><p>${err.message}</p></div>`;
            }
        }

        // Render Cards
        function renderPodcasts() {
            const filtered = allPodcasts.filter(p => {
                const matchesTab = activeFilter === 'all' || p.category === activeFilter;
                const matchesSearch = p.title.toLowerCase().includes(searchQuery) ||
                                      p.topic.toLowerCase().includes(searchQuery) ||
                                      p.summary.toLowerCase().includes(searchQuery);
                return matchesTab && matchesSearch;
            });

            if (filtered.length === 0) {
                grid.innerHTML = '';
                emptyState.style.display = 'block';
                return;
            }

            emptyState.style.display = 'none';
            
            grid.innerHTML = filtered.map(p => {
                const isPlayingThis = currentPodcast && currentPodcast.filename === p.filename;
                const playBtnState = isPlayingThis && !audio.paused ? 'pause' : 'play';
                const fileDate = new Date(p.mtime * 1000).toLocaleDateString(undefined, {month: 'short', day: 'numeric', year: 'numeric'});
                const sizeMb = (p.size / (1024 * 1024)).toFixed(1);
                
                return `
                    <div class="podcast-card ${isPlayingThis ? 'playing' : ''}" data-file="${p.filename}">
                        <div class="card-header">
                            <span class="topic-badge" title="${p.topic}">${p.topic}</span>
                            <span class="category-tag">${p.category}</span>
                        </div>
                        <h2 class="card-title" title="${p.title}">${p.title}</h2>
                        <p class="card-summary" id="summary-${p.filename.replace(/[^a-zA-Z0-9]/g, '')}">${p.summary}</p>
                        <button class="read-more-btn" onclick="toggleSummary('${p.filename}')" id="rm-btn-${p.filename.replace(/[^a-zA-Z0-9]/g, '')}">
                            Read More
                        </button>
                        <div class="card-footer">
                            <div class="meta-info">
                                <span>${fileDate}</span>
                                <span>${sizeMb} MB</span>
                            </div>
                            <button class="play-card-btn" onclick="togglePlayPodcast('${p.filename}')" title="Play Episode">
                                ${playBtnState === 'play' ? `
                                    <svg viewBox="0 0 24 24"><path d="M8 5v14l11-7z"/></svg>
                                ` : `
                                    <svg viewBox="0 0 24 24"><path d="M6 19h4V5H6v14zm8-14v14h4V5h-4z"/></svg>
                                `}
                            </button>
                        </div>
                    </div>
                `;
            }).join('');
        }

        // Toggle Expandable Summaries
        window.toggleSummary = function(filename) {
            const cleanId = filename.replace(/[^a-zA-Z0-9]/g, '');
            const el = document.getElementById(`summary-${cleanId}`);
            const btn = document.getElementById(`rm-btn-${cleanId}`);
            if (el.classList.contains('expanded')) {
                el.classList.remove('expanded');
                btn.textContent = 'Read More';
            } else {
                el.classList.add('expanded');
                btn.textContent = 'Read Less';
            }
        };

        // Filter / Search Handlers
        filterTabs.addEventListener('click', e => {
            if (!e.target.classList.contains('tab-btn')) return;
            document.querySelectorAll('.tab-btn').forEach(btn => btn.classList.remove('active'));
            e.target.classList.add('active');
            activeFilter = e.target.dataset.filter;
            renderPodcasts();
        });

        searchInput.addEventListener('input', e => {
            searchQuery = e.target.value.toLowerCase().trim();
            renderPodcasts();
        });

        // Toggle audio play/pause
        window.togglePlayPodcast = function(filename) {
            const podcast = allPodcasts.find(p => p.filename === filename);
            if (!podcast) return;

            if (currentPodcast && currentPodcast.filename === filename) {
                if (audio.paused) {
                    audio.play();
                } else {
                    audio.pause();
                }
            } else {
                currentPodcast = podcast;
                audio.src = `/audio/${encodeURIComponent(filename)}`;
                audio.play();
                
                playerTitle.textContent = podcast.title;
                playerTopic.textContent = podcast.topic;
                
                if (podcast.url) {
                    playerSourceLink.href = podcast.url;
                    playerSourceLink.style.display = 'inline-flex';
                } else {
                    playerSourceLink.style.display = 'none';
                }
                
                playerBar.style.display = 'block';
            }
            renderPodcasts();
        };

        // Main Player Controls binding
        btnPlay.addEventListener('click', () => {
            if (!currentPodcast) return;
            if (audio.paused) {
                audio.play();
            } else {
                audio.pause();
            }
        });

        btnBack.addEventListener('click', () => {
            audio.currentTime = Math.max(0, audio.currentTime - 15);
        });

        btnForward.addEventListener('click', () => {
            audio.currentTime = Math.min(audio.duration || 0, audio.currentTime + 15);
        });

        // Audio Listeners for Playback state
        audio.addEventListener('play', () => {
            playIcon.style.display = 'none';
            pauseIcon.style.display = 'block';
            renderPodcasts();
        });

        audio.addEventListener('pause', () => {
            playIcon.style.display = 'block';
            pauseIcon.style.display = 'none';
            renderPodcasts();
        });

        audio.addEventListener('timeupdate', () => {
            if (isSeeking) return;
            const cur = audio.currentTime || 0;
            const dur = audio.duration || 0;
            currentTimeEl.textContent = formatTime(cur);
            if (dur > 0) {
                durationTimeEl.textContent = formatTime(dur);
                const pct = (cur / dur) * 100;
                progressFilled.style.width = `${pct}%`;
                progressHandle.style.left = `${pct}%`;
            }
        });

        audio.addEventListener('durationchange', () => {
            const dur = audio.duration || 0;
            if (dur > 0) durationTimeEl.textContent = formatTime(dur);
        });

        audio.addEventListener('ended', () => {
            playIcon.style.display = 'block';
            pauseIcon.style.display = 'none';
            progressFilled.style.width = '0%';
            progressHandle.style.left = '0%';
            currentTimeEl.textContent = '0:00';
            renderPodcasts();
        });

        // Custom Slider Scrubbing logic
        function updateScrub(e) {
            const rect = progressContainer.getBoundingClientRect();
            const pct = Math.min(1, Math.max(0, (e.clientX - rect.left) / rect.width));
            progressFilled.style.width = `${pct * 100}%`;
            progressHandle.style.left = `${pct * 100}%`;
            currentTimeEl.textContent = formatTime(pct * (audio.duration || 0));
            return pct;
        }

        progressContainer.addEventListener('mousedown', e => {
            isSeeking = true;
            const pct = updateScrub(e);
            
            function onMouseMove(moveEvent) {
                updateScrub(moveEvent);
            }
            
            function onMouseUp(upEvent) {
                const finalPct = updateScrub(upEvent);
                audio.currentTime = finalPct * (audio.duration || 0);
                isSeeking = false;
                document.removeEventListener('mousemove', onMouseMove);
                document.removeEventListener('mouseup', onMouseUp);
            }
            
            document.addEventListener('mousemove', onMouseMove);
            document.addEventListener('mouseup', onMouseUp);
        });

        progressContainer.addEventListener('touchstart', e => {
            isSeeking = true;
            const touch = e.touches[0];
            const rect = progressContainer.getBoundingClientRect();
            let pct = Math.min(1, Math.max(0, (touch.clientX - rect.left) / rect.width));
            progressFilled.style.width = `${pct * 100}%`;
            progressHandle.style.left = `${pct * 100}%`;
            
            function onTouchMove(moveEvent) {
                const t = moveEvent.touches[0];
                pct = Math.min(1, Math.max(0, (t.clientX - rect.left) / rect.width));
                progressFilled.style.width = `${pct * 100}%`;
                progressHandle.style.left = `${pct * 100}%`;
                currentTimeEl.textContent = formatTime(pct * (audio.duration || 0));
            }
            
            function onTouchEnd() {
                audio.currentTime = pct * (audio.duration || 0);
                isSeeking = false;
                document.removeEventListener('touchmove', onTouchMove);
                document.removeEventListener('touchend', onTouchEnd);
            }
            
            document.addEventListener('touchmove', onTouchMove);
            document.addEventListener('touchend', onTouchEnd);
        });

        // Speed Menu Controls
        speedBtn.addEventListener('click', e => {
            e.stopPropagation();
            speedMenu.classList.toggle('show');
        });

        document.addEventListener('click', () => {
            speedMenu.classList.remove('show');
        });

        speedMenu.addEventListener('click', e => {
            if (!e.target.classList.contains('speed-option')) return;
            const speed = parseFloat(e.target.dataset.speed);
            audio.playbackRate = speed;
            speedBtn.textContent = `${speed.toFixed(1)}x`;
            
            document.querySelectorAll('.speed-option').forEach(opt => opt.classList.remove('active'));
            e.target.classList.add('active');
        });

        // Volume Controls
        volumeSlider.addEventListener('input', e => {
            const val = parseFloat(e.target.value);
            audio.volume = val;
            updateVolumeIcon(val);
        });

        let lastVolume = 1;
        volumeIcon.addEventListener('click', () => {
            if (audio.volume > 0) {
                lastVolume = audio.volume;
                audio.volume = 0;
                volumeSlider.value = 0;
                updateVolumeIcon(0);
            } else {
                audio.volume = lastVolume;
                volumeSlider.value = lastVolume;
                updateVolumeIcon(lastVolume);
            }
        });

        function updateVolumeIcon(val) {
            if (val === 0) {
                volumeIcon.innerHTML = '<path d="M16.5 12c0-1.77-1.02-3.29-2.5-4.03v2.21l2.45 2.45c.03-.21.05-.42.05-.63zm2.5 0c0 .94-.2 1.82-.54 2.64l1.51 1.51C20.63 14.91 21 13.5 21 12c0-4.28-2.99-7.86-7-8.77v2.06c2.89.86 5 3.54 5 6.71zM4.27 3L3 4.27 7.73 9H3v6h4l5 5v-6.73l4.25 4.25c-.67.52-1.42.93-2.25 1.18v2.06c1.38-.31 2.63-.95 3.69-1.81L19.73 21 21 19.73l-9-9L4.27 3zM12 4L9.91 6.09 12 8.18V4z"/>';
            } else if (val < 0.5) {
                volumeIcon.innerHTML = '<path d="M7 9v6h4l5 5V4L7 9H3zm11.5 3c0-1.77-1.02-3.29-2.5-4.03v8.05c1.48-.73 2.5-2.25 2.5-4.02z"/>';
            } else {
                volumeIcon.innerHTML = '<path d="M3 9v6h4l5 5V4L7 9H3zm13.5 3c0-1.77-1.02-3.29-2.5-4.03v8.05c1.48-.73 2.5-2.25 2.5-4.02zM14 3.23v2.06c2.89.86 5 3.54 5 6.71s-2.11 5.85-5 6.71v2.06c4.01-.91 7-4.49 7-8.77s-2.99-7.86-7-8.77z"/>';
            }
        }

        // Initialize
        fetchPodcasts();
    </script>
</body>
</html>
"""
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(html_content.encode('utf-8'))

def get_local_ips():
    import socket
    ips = []
    
    # Try to get local network IP
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        if local_ip:
            ips.append(local_ip)
        s.close()
    except Exception:
        pass

    # Try resolving hostname IPs
    try:
        hostname = socket.gethostname()
        for ip in socket.gethostbyname_ex(hostname)[2]:
            if not ip.startswith('127.') and ip not in ips:
                ips.append(ip)
    except Exception:
        pass
        
    return list(dict.fromkeys(ips))

def main():
    global PORT, VAULT_DIR, ATTACHMENTS_DIR
    import argparse
    parser = argparse.ArgumentParser(description="Obsidian Podcast Tailnet Server")
    parser.add_argument('--port', type=int, default=PORT, help=f"Port to bind server (default: {PORT})")
    parser.add_argument('--vault', type=str, default=VAULT_DIR, help="Path to Obsidian vault")
    args = parser.parse_args()
    
    PORT = args.port
    VAULT_DIR = os.path.abspath(args.vault)
    ATTACHMENTS_DIR = os.path.join(VAULT_DIR, "99_System", "Attachments")
    
    print("=" * 60)
    print(f"[*] Starting Obsidian Podcast Server...")
    print(f"[-] Vault Directory:      {VAULT_DIR}")
    print(f"[-] Attachments Directory: {ATTACHMENTS_DIR}")
    print(f"[-] Port:                  {PORT}")
    
    try:
        podcasts = get_podcast_list()
        print(f"[+] Found and indexed {len(podcasts)} NotebookLM podcasts.")
    except Exception as e:
        print(f"[!] Error running initial index: {e}")
        
    print(f"[+] Server active on:")
    print(f"    - http://localhost:{PORT}")
    for ip in get_local_ips():
        print(f"    - http://{ip}:{PORT}")
    print("=" * 60)
    
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("0.0.0.0", PORT), PodcastHTTPHandler) as httpd:
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n[-] Shutting down podcast server.")

if __name__ == "__main__":
    main()
