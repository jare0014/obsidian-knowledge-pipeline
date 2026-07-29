import os
import re
import sys
import json
import shutil
import subprocess
import urllib.parse
import http.server
import socketserver
import xml.etree.ElementTree as ET
import io
from datetime import datetime
import email.utils

# If running without console, redirect stdout/stderr to podcast_server.log
LOG_FILE = os.path.join(os.path.dirname(__file__), "podcast_server.log")
try:
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    if hasattr(sys.stderr, 'reconfigure'):
        sys.stderr.reconfigure(encoding='utf-8')
    if sys.stdout is None or not hasattr(sys.stdout, "write"):
        sys.stdout = open(LOG_FILE, "a", encoding="utf-8")
    if sys.stderr is None or not hasattr(sys.stderr, "write"):
        sys.stderr = open(LOG_FILE, "a", encoding="utf-8")
except Exception:
    pass

# Default Paths (relative to the Obsidian vault root)
PORT = 8085

def find_vault_root(start_path):
    curr = os.path.abspath(start_path)
    while curr and os.path.dirname(curr) != curr:
        if os.path.basename(curr) != ".obsidian" and os.path.exists(os.path.join(curr, ".obsidian")):
            return curr
        curr = os.path.dirname(curr)
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

VAULT_DIR = find_vault_root(__file__)

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
os.makedirs(ATTACHMENTS_DIR, exist_ok=True)
os.makedirs(os.path.join(ATTACHMENTS_DIR, "Quizzes"), exist_ok=True)

def clean_title(title):
    clean = re.sub(r'[\\/*?:"<>|]', '', title)
    clean = " ".join(clean.split())
    return clean[:80]

def fetch_notebooklm_quiz(notebook_id, note_path=""):
    """
    Fetch quiz questions for a notebook using notebooklm-py if available,
    check 99_System/Attachments/Quizzes for saved JSON artifacts, or generate structured quiz questions.
    """
    quizzes_dir = os.path.join(VAULT_DIR, "99_System", "Attachments", "Quizzes")
    if note_path:
        note_basename = os.path.splitext(os.path.basename(note_path))[0]
        clean_base = re.sub(r'Podcast(\s*\(\d+\))?$', '', note_basename, flags=re.IGNORECASE).strip()

        # Check for error json file
        for err_candidate in [f"{note_basename} Quiz_error.json", f"{clean_title(clean_base)} Quiz_error.json"]:
            err_path = os.path.join(quizzes_dir, err_candidate)
            if os.path.exists(err_path):
                try:
                    with open(err_path, "r", encoding="utf-8") as f:
                        err_data = json.load(f)
                        err_data["exists"] = False
                        return err_data
                except Exception:
                    pass

        candidates = [
            f"{note_basename} Quiz.json",
            f"{clean_title(note_basename)} Quiz.json",
            f"{clean_base} Quiz.json",
            f"{clean_title(clean_base)} Quiz.json"
        ]
        for quiz_json_filename in candidates:
            quiz_json_path = os.path.join(quizzes_dir, quiz_json_filename)
            if os.path.exists(quiz_json_path):
                try:
                    with open(quiz_json_path, "r", encoding="utf-8") as f:
                        quiz_data = json.load(f)
                        if quiz_data and "questions" in quiz_data and len(quiz_data["questions"]) > 0:
                            quiz_data["exists"] = True
                            return quiz_data
                except Exception:
                    pass

        # Search directory for matching title/notebook_id
        if os.path.exists(quizzes_dir):
            norm_target = normalize_name(clean_base)
            for q_file in os.listdir(quizzes_dir):
                if q_file.endswith(".json") and not q_file.endswith("_error.json"):
                    q_base = os.path.splitext(q_file)[0].replace(" Quiz", "")
                    if normalize_name(q_base) == norm_target or norm_target in normalize_name(q_base):
                        try:
                            with open(os.path.join(quizzes_dir, q_file), "r", encoding="utf-8") as f:
                                quiz_data = json.load(f)
                                if quiz_data and "questions" in quiz_data and len(quiz_data["questions"]) > 0:
                                    quiz_data["exists"] = True
                                    return quiz_data
                        except Exception:
                            pass

    auth_file = os.path.expanduser(r"~\.notebooklm\profiles\default\storage_state.json")
    if not os.path.exists(auth_file) or os.path.getsize(auth_file) < 50:
        return {
            "exists": False,
            "error": "NotebookLM is not authenticated. Please run 'notebooklm login' in your system terminal (PowerShell / Command Prompt) to log in to Google NotebookLM.",
            "title": os.path.splitext(os.path.basename(note_path))[0] if note_path else "Knowledge Base Note",
            "questions": []
        }

    note_title = os.path.splitext(os.path.basename(note_path))[0] if note_path else "Knowledge Base Note"
    return {
        "exists": False,
        "title": note_title,
        "notebook_id": notebook_id,
        "note_path": note_path,
        "questions": [],
        "message": f"Quiz not yet generated for '{note_title}'."
    }

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
        # Skip hidden, system, and junction project directories to prevent infinite recursive loop
        dirs[:] = [d for d in dirs if not d.startswith(".") and d not in ("venv", ".venv", "node_modules", ".trash", "04_Projects", ".agents", ".obsidian")]
        
        for file in files:
            if not file.endswith(".md"):
                continue
            
            note_path = os.path.join(root, file)
            rel_path = os.path.relpath(note_path, vault_path).replace("\\", "/")
            
            # Determine folder category
            if rel_path.startswith("01_Inbox/"):
                category = "inbox"
            elif rel_path.startswith("01_Incubator/"):
                category = "incubator"
            elif rel_path.startswith("03_Knowledge/"):
                category = "knowledge"
            elif rel_path.startswith("99_Archive/"):
                category = "archive"
            else:
                category = "other"
            
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
                'url': metadata.get('url') or '',
                'notebook_id': metadata.get('notebook_id') or metadata.get('notebooklm_id') or ''
            }
            
            # Index by normalized base name
            norm_title = normalize_name(note_title)
            basename_map[norm_title] = note_info
            
            # Index by any embedded audio files or linked assets inside the note
            # Matches ![[File Name Podcast.mp3]] or [[99_System/Attachments/...]]
            links_and_embeds = re.findall(r'!?\[\[(.*?)(?:\|.*?)?\]\]', content)
            for link in links_and_embeds:
                clean_link = os.path.basename(link)
                embed_map[clean_link] = note_info
                clean_base = os.path.splitext(clean_link)[0]
                embed_map[clean_base] = note_info

    return embed_map, basename_map

def get_podcast_list():
    """Scan vault directories for audio files (.mp3, .m4a, .wav, .ogg, .flac) and match metadata from markdown notes."""
    embed_map, basename_map = scan_notes_metadata(VAULT_DIR)
    podcasts = []
    matched_note_titles = set()
    
    AUDIO_EXTENSIONS = ('.mp3', '.m4a', '.wav', '.ogg', '.flac', '.aac')
    seen_files = set()

    for root, dirs, files in os.walk(VAULT_DIR):
        # Skip hidden, system, and junction project directories to prevent infinite recursive loop
        dirs[:] = [d for d in dirs if not d.startswith(".") and d not in ("venv", ".venv", "node_modules", ".trash", "04_Projects", ".agents", ".obsidian")]
        
        for item in files:
            if not item.lower().endswith(AUDIO_EXTENSIONS):
                continue
                
            file_path = os.path.join(root, item)
            if not os.path.isfile(file_path) or file_path in seen_files:
                continue
            seen_files.add(file_path)
                
            # Get basic file details
            stat = os.stat(file_path)
            size = stat.st_size
            mtime = stat.st_mtime
            
            # Clean title from filename
            clean_base = re.sub(r'Podcast(\s*\(\d+\))?\.mp3$', '', item, flags=re.IGNORECASE).strip()
            clean_base = re.sub(r'\.(mp3|m4a|wav|ogg|flac|aac)$', '', clean_base, flags=re.IGNORECASE).strip()
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
                        if len(norm_title) >= 10 and (norm_title in norm_clean or norm_clean in norm_title):
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
                notebook_id = matched_note['notebook_id']
                matched_note_titles.add(matched_note['title'])
            else:
                title = clean_base if clean_base else item
                summary = "Audio asset in vault."
                topic = "General"
                rel_p = os.path.relpath(file_path, VAULT_DIR).replace("\\", "/")
                if rel_p.startswith("00_Imports/"):
                    category = "imports"
                elif rel_p.startswith("01_Inbox/"):
                    category = "inbox"
                elif rel_p.startswith("01_Incubator/"):
                    category = "incubator"
                elif rel_p.startswith("03_Knowledge/"):
                    category = "knowledge"
                else:
                    category = "archive"
                url = ""
                notebook_id = ""
                
            podcasts.append({
                'filename': item,
                'rel_path': matched_note['rel_path'] if matched_note else os.path.relpath(file_path, VAULT_DIR).replace("\\", "/"),
                'title': title,
                'summary': summary,
                'topic': topic,
                'category': category,
                'url': url,
                'notebook_id': notebook_id,
                'size': size,
                'mtime': mtime
            })

    # Include non-audio notes from stage folders if they have a URL or notebook_id (for NotebookLM generation)
    for norm_title, info in basename_map.items():
        if info['title'] not in matched_note_titles:
            # Skip non-audio notes outside of pipeline stage folders
            if info['category'] == 'other':
                continue
            # Skip plain text notes that lack both a URL and NotebookLM notebook_id
            has_url = bool(info.get('url') and str(info['url']).strip())
            has_notebook = bool(info.get('notebook_id') and str(info['notebook_id']).strip())
            if not has_url and not has_notebook:
                continue
            try:
                mtime = os.path.getmtime(info['path']) if os.path.exists(info['path']) else 0
            except Exception:
                mtime = 0
            podcasts.append({
                'filename': '',
                'rel_path': info['rel_path'],
                'title': info['title'],
                'summary': info['summary'],
                'topic': info['topic'],
                'category': info['category'],
                'url': info['url'],
                'notebook_id': info['notebook_id'],
                'size': 0,
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

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, Authorization')
        self.end_headers()

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
            
        # 1b. API: Fetch NotebookLM Quiz
        if path.startswith('/api/quiz'):
            try:
                query_params = urllib.parse.parse_qs(parsed_url.query)
                notebook_id = query_params.get('notebook_id', [''])[0]
                note_path = query_params.get('note_path', [''])[0]
                
                quiz_data = fetch_notebooklm_quiz(notebook_id, note_path)
                body_bytes = json.dumps(quiz_data).encode('utf-8')
                
                self.send_response(200)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.send_header('Content-Length', str(len(body_bytes)))
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(body_bytes)
            except Exception as e:
                err_bytes = json.dumps({'error': str(e), 'title': 'Quiz Error', 'questions': []}).encode('utf-8')
                self.send_response(500)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.send_header('Content-Length', str(len(err_bytes)))
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(err_bytes)
            return

        # 2. RSS Feed: feed.xml
        if path in ('/feed.xml', '/rss', '/feed'):
            self.serve_rss_feed()
            return
            
        # 3. Audio Streaming (with HTTP 206 Range Request support)
        if path.startswith('/audio/'):
            filename = urllib.parse.unquote(path[7:])
            filepath = os.path.join(ATTACHMENTS_DIR, filename)
            if not os.path.exists(filepath):
                filepath = os.path.join(VAULT_DIR, filename)
            if not os.path.exists(filepath):
                for root, _, files in os.walk(VAULT_DIR):
                    if filename in files:
                        filepath = os.path.join(root, filename)
                        break
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

    def _send_json(self, data, status=200):
        body_bytes = json.dumps(data).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body_bytes)))
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(body_bytes)

    def do_POST(self):
        parsed_url = urllib.parse.urlparse(self.path)
        path = parsed_url.path
        
        content_length = int(self.headers.get('Content-Length', 0))
        post_data = self.rfile.read(content_length).decode('utf-8') if content_length > 0 else "{}"
        try:
            body = json.loads(post_data)
        except Exception:
            body = {}
            
        if path == '/api/add_note':
            note_rel_path = body.get('note_path', '')
            note_text = body.get('text', '')
            if not note_rel_path or not note_text:
                self._send_json({'error': 'Missing note_path or text'}, status=400)
                return
                
            full_path = os.path.join(VAULT_DIR, note_rel_path) if not os.path.isabs(note_rel_path) else note_rel_path
            if not os.path.exists(full_path) or full_path.lower().endswith(('.mp3', '.m4a', '.wav', '.ogg', '.flac', '.aac')):
                clean_base = os.path.splitext(os.path.basename(note_rel_path))[0]
                clean_base = re.sub(r'Podcast(\s*\(\d+\))?$', '', clean_base, flags=re.IGNORECASE).strip()
                embed_map, basename_map = scan_notes_metadata(VAULT_DIR)
                matched = basename_map.get(normalize_name(clean_base)) or embed_map.get(clean_base) or embed_map.get(os.path.basename(note_rel_path))
                if matched:
                    full_path = matched['path']

            if os.path.exists(full_path):
                date_str = datetime.now().strftime("%Y-%m-%d %H:%M")
                append_block = f"\n\n### 📝 Note Added ({date_str})\n{note_text}\n"
                with open(full_path, "a", encoding="utf-8") as f:
                    f.write(append_block)
                self._send_json({'success': True, 'message': f'Appended note to {os.path.basename(full_path)}'})
            else:
                self._send_json({'error': f'Note file not found: {os.path.basename(note_rel_path)}'}, status=404)
            return

        if path == '/api/move_note':
            note_rel_path = body.get('note_path', '')
            dest_stage = body.get('destination', '') # 'inbox', 'incubator', 'knowledge'
            if not note_rel_path or not dest_stage:
                self._send_json({'error': 'Missing note_path or destination'}, status=400)
                return
                
            src_full = os.path.join(VAULT_DIR, note_rel_path) if not os.path.isabs(note_rel_path) else note_rel_path
            if not os.path.exists(src_full) or src_full.lower().endswith(('.mp3', '.m4a', '.wav', '.ogg', '.flac', '.aac')):
                clean_base = os.path.splitext(os.path.basename(note_rel_path))[0]
                clean_base = re.sub(r'Podcast(\s*\(\d+\))?$', '', clean_base, flags=re.IGNORECASE).strip()
                embed_map, basename_map = scan_notes_metadata(VAULT_DIR)
                matched = basename_map.get(normalize_name(clean_base)) or embed_map.get(clean_base) or embed_map.get(os.path.basename(note_rel_path))
                if matched:
                    src_full = matched['path']

            if not os.path.exists(src_full):
                self._send_json({'error': f'Source markdown note not found: {os.path.basename(note_rel_path)}'}, status=404)
                return
                
            folder_map = {
                'inbox': '01_Inbox',
                'incubator': '01_Incubator',
                'knowledge': '03_Knowledge'
            }
            dest_folder_name = folder_map.get(dest_stage, '01_Inbox')
            dest_dir = os.path.join(VAULT_DIR, dest_folder_name)
            if not os.path.exists(dest_dir):
                os.makedirs(dest_dir)
                
            dest_full = os.path.join(dest_dir, os.path.basename(src_full))
            shutil.move(src_full, dest_full)
            new_rel_path = os.path.relpath(dest_full, VAULT_DIR).replace("\\", "/")
            
            # If moved to Inbox -> trigger Podcast & MindMap generation if missing
            if dest_stage == 'inbox':
                python_bin = sys.executable
                script_path = os.path.join(os.path.dirname(__file__), 'generate_artifact.py')
                sub_env = os.environ.copy()
                sub_env["PYTHONIOENCODING"] = "utf-8"
                subprocess.Popen([python_bin, script_path, dest_full, 'audio'], shell=False, env=sub_env)
                subprocess.Popen([python_bin, script_path, dest_full, 'mind-map'], shell=False, env=sub_env)

            # If moved to Knowledge -> trigger Quiz generation if missing
            if dest_stage == 'knowledge':
                python_bin = sys.executable
                script_path = os.path.join(os.path.dirname(__file__), 'generate_artifact.py')
                sub_env = os.environ.copy()
                sub_env["PYTHONIOENCODING"] = "utf-8"
                subprocess.Popen([python_bin, script_path, dest_full, 'quiz'], shell=False, env=sub_env)

            self._send_json({'success': True, 'new_path': new_rel_path, 'message': f'Moved note to {dest_folder_name}'})
            return

        if path == '/api/generate_artifact':
            note_rel_path = body.get('note_path', '')
            artifact_type = body.get('artifact_type', 'audio')
            if not note_rel_path:
                self._send_json({'error': 'Missing note_path'}, status=400)
                return
            src_full = os.path.join(VAULT_DIR, note_rel_path) if not os.path.isabs(note_rel_path) else note_rel_path
            if not os.path.exists(src_full):
                self._send_json({'error': 'Note file not found'}, status=404)
                return
            
            python_bin = sys.executable
            script_path = os.path.join(os.path.dirname(__file__), 'generate_artifact.py')
            sub_env = os.environ.copy()
            sub_env["PYTHONIOENCODING"] = "utf-8"
            subprocess.Popen([python_bin, script_path, src_full, artifact_type], shell=False, env=sub_env)
            self._send_json({'success': True, 'message': f'Triggered {artifact_type} generation in background for {os.path.basename(src_full)}'})
            return
            
        self._send_json({'error': 'Not found'}, status=404)

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

        /* NotebookLM Interactive Quiz Modal */
        .quiz-card-btn {
            padding: 6px 12px;
            border-radius: 8px;
            background: rgba(139, 92, 246, 0.2);
            border: 1px solid rgba(139, 92, 246, 0.4);
            color: #c084fc;
            font-size: 0.85rem;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.2s;
        }

        .quiz-card-btn:hover {
            background: rgba(139, 92, 246, 0.35);
            color: white;
            box-shadow: 0 0 10px rgba(139, 92, 246, 0.4);
        }

        .modal-overlay {
            position: fixed;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            background: rgba(15, 23, 42, 0.85);
            backdrop-filter: blur(12px);
            z-index: 9999;
            display: flex;
            align-items: center;
            justify-content: center;
            opacity: 0;
            pointer-events: none;
            transition: opacity 0.3s ease;
        }

        .modal-overlay.active {
            opacity: 1;
            pointer-events: auto;
        }

        .quiz-modal {
            background: #1e293b;
            border: 1px solid rgba(255, 255, 255, 0.12);
            border-radius: 20px;
            width: 90%;
            max-width: 620px;
            padding: 30px;
            box-shadow: 0 20px 50px rgba(0, 0, 0, 0.5);
            display: flex;
            flex-direction: column;
            gap: 20px;
            position: relative;
        }

        .quiz-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
        }

        .quiz-counter {
            font-size: 0.9rem;
            font-weight: 600;
            color: var(--text-muted);
        }

        .quiz-close {
            background: transparent;
            border: none;
            color: var(--text-secondary);
            font-size: 1.5rem;
            cursor: pointer;
            padding: 0 5px;
        }

        .quiz-question-text {
            font-size: 1.15rem;
            font-weight: 600;
            line-height: 1.4;
            color: var(--text-primary);
        }

        .quiz-options-list {
            display: flex;
            flex-direction: column;
            gap: 12px;
        }

        .quiz-option-btn {
            background: rgba(255, 255, 255, 0.05);
            border: 1px solid rgba(255, 255, 255, 0.08);
            border-radius: 12px;
            padding: 14px 18px;
            color: var(--text-primary);
            font-size: 0.95rem;
            text-align: left;
            cursor: pointer;
            transition: all 0.2s;
            display: flex;
            align-items: center;
            gap: 10px;
        }

        .quiz-option-btn:hover {
            background: rgba(255, 255, 255, 0.1);
            border-color: rgba(255, 255, 255, 0.2);
        }

        .quiz-option-btn.selected-correct {
            background: rgba(16, 185, 129, 0.25);
            border-color: #10b981;
            color: #34d399;
        }

        .quiz-option-btn.selected-incorrect {
            background: rgba(239, 68, 68, 0.25);
            border-color: #ef4444;
            color: #f87171;
        }

        .quiz-footer {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-top: 10px;
        }

        .quiz-hint-toggle {
            color: var(--text-muted);
            font-size: 0.85rem;
            cursor: pointer;
            text-decoration: underline;
        }

        .quiz-next-btn {
            background: #4f46e5;
            color: white;
            border: none;
            border-radius: 20px;
            padding: 8px 24px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.2s;
        }

        .quiz-next-btn:hover {
            background: #6366f1;
            box-shadow: 0 0 15px rgba(99, 102, 241, 0.5);
        }
    </style>
</head>
<body>

    <!-- Quiz Modal HTML -->
    <div class="modal-overlay" id="quiz-modal-overlay">
        <div class="quiz-modal">
            <div class="quiz-header">
                <span class="quiz-counter" id="quiz-counter">1 / 10</span>
                <button class="quiz-close" onclick="closeQuizModal()">&times;</button>
            </div>
            <div class="quiz-question-text" id="quiz-question-text">Loading question...</div>
            <div class="quiz-options-list" id="quiz-options-list"></div>
            <div class="quiz-footer">
                <span class="quiz-hint-toggle" id="quiz-hint-btn" onclick="toggleQuizHint()">Hint &or;</span>
                <button class="quiz-next-btn" id="quiz-next-btn" onclick="nextQuizQuestion()">Next</button>
            </div>
            <div id="quiz-hint-box" style="display:none; font-size:0.85rem; color:var(--text-muted); padding:8px; background:rgba(0,0,0,0.2); border-radius:8px;"></div>
        </div>
    </div>

    <!-- Add Note Modal HTML -->
    <div class="modal-overlay" id="note-modal-overlay">
        <div class="quiz-modal" style="max-width: 520px;">
            <div class="quiz-header">
                <h3 style="color: #fff; margin:0; font-size: 1.1rem;">📝 Add Note to Markdown File</h3>
                <button class="quiz-close" onclick="closeNoteModal()">&times;</button>
            </div>
            <div style="padding: 16px;">
                <textarea id="note-text-input" style="width: 100%; height: 130px; background: rgba(0,0,0,0.3); border: 1px solid var(--border-color); color: #fff; padding: 12px; border-radius: 8px; font-family: inherit; font-size: 0.95rem; resize: vertical; box-sizing: border-box;" placeholder="Type your note content here..."></textarea>
            </div>
            <div class="quiz-footer" style="justify-content: flex-end; gap: 8px;">
                <button class="action-btn demote-btn" onclick="closeNoteModal()">Cancel</button>
                <button class="action-btn promote-btn" id="save-note-btn">Save Note</button>
            </div>
        </div>
    </div>

    <!-- Confirm Modal HTML -->
    <div class="modal-overlay" id="confirm-modal-overlay">
        <div class="quiz-modal" style="max-width: 480px;">
            <div class="quiz-header">
                <h3 id="confirm-modal-title" style="color: #fff; margin:0; font-size: 1.1rem;">Confirm Action</h3>
                <button class="quiz-close" onclick="closeConfirmModal()">&times;</button>
            </div>
            <div style="padding: 16px;">
                <p id="confirm-modal-message" style="color: var(--text-secondary); line-height: 1.5; margin: 0; font-size: 0.95rem;"></p>
            </div>
            <div class="quiz-footer" style="justify-content: flex-end; gap: 8px;">
                <button class="action-btn demote-btn" onclick="closeConfirmModal()">Cancel</button>
                <button class="action-btn promote-btn" id="confirm-modal-ok-btn">Proceed</button>
            </div>
        </div>
    </div>

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
                <button class="tab-btn" data-filter="inbox">📥 Inbox</button>
                <button class="tab-btn" data-filter="incubator">❔ Incubator</button>
                <button class="tab-btn" data-filter="knowledge">🎓 Knowledge</button>
                <button class="tab-btn" data-filter="archive">📦 Archive</button>
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

        function getApiUrl(path) {
            const origin = window.location.origin && window.location.origin.startsWith('http') ? window.location.origin : 'http://localhost:8085';
            return origin + path;
        }

        // Fetch Podcasts
        async function fetchPodcasts() {
            try {
                const res = await fetch(getApiUrl('/api/podcasts'));
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
                
                const encRelPath = encodeURIComponent(p.rel_path || '');
                const encFilename = encodeURIComponent(p.filename || '');
                const encNotebookId = encodeURIComponent(p.notebook_id || '');

                const hasAudio = Boolean(p.filename && p.filename.trim());
                const playBtnHtml = hasAudio ? `
                    <button class="play-card-btn" data-filename="${encFilename}" data-relpath="${encRelPath}" onclick="togglePlayPodcastByEl(this)" title="Play Episode">
                        ${playBtnState === 'play' ? '<svg viewBox="0 0 24 24"><path d="M8 5v14l11-7z"/></svg>' : '<svg viewBox="0 0 24 24"><path d="M6 19h4V5H6v14zm8-14v14h4V5h-4z"/></svg>'}
                    </button>
                ` : `
                    <button class="action-btn promote-btn" data-filename="${encFilename}" data-relpath="${encRelPath}" onclick="togglePlayPodcastByEl(this)" title="Generate Podcast Audio with NotebookLM">🎙️ Generate Audio</button>
                `;

                return `
                    <div class="podcast-card ${isPlayingThis ? 'playing' : ''}" data-file="${encFilename}">
                        <div class="card-header">
                            <span class="topic-badge" title="${p.topic}">${p.topic}</span>
                            <span class="category-tag">${p.category}</span>
                        </div>
                        <h2 class="card-title" title="${p.title}">${p.title}</h2>
                        <p class="card-summary" id="summary-${p.filename.replace(/[^a-zA-Z0-9]/g, '')}">${p.summary}</p>
                        <button class="read-more-btn" data-filename="${encFilename}" onclick="toggleSummaryByEl(this)" id="rm-btn-${p.filename.replace(/[^a-zA-Z0-9]/g, '')}">
                            Read More
                        </button>
                        <div class="card-footer">
                            <div class="meta-info">
                                <span>${fileDate}</span>
                                <span>${sizeMb} MB</span>
                            </div>
                            <div style="display: flex; gap: 8px; align-items: center; flex-wrap: wrap;">
                                ${p.category === 'imports' ? `
                                    <button class="action-btn promote-btn" data-relpath="${encRelPath}" onclick="moveNoteByEl(this, 'inbox')" title="Promote to Inbox">➡️ Promote to Inbox</button>
                                ` : p.category === 'inbox' ? `
                                    ${playBtnHtml}
                                    <button class="action-btn note-btn" data-relpath="${encRelPath}" onclick="promptAddNoteByEl(this)" title="Add Note to File">📝 Add Note</button>
                                    <button class="action-btn promote-btn" data-relpath="${encRelPath}" onclick="moveNoteByEl(this, 'knowledge')" title="Promote to Knowledge">🎓 Promote to Knowledge</button>
                                    <button class="action-btn demote-btn" data-relpath="${encRelPath}" onclick="moveNoteByEl(this, 'incubator')" title="Demote to Incubator">❔ Demote to Incubator</button>
                                ` : p.category === 'knowledge' ? `
                                    ${playBtnHtml}
                                    <button class="action-btn note-btn" data-relpath="${encRelPath}" onclick="promptAddNoteByEl(this)" title="Add Note to File">📝 Add Note</button>
                                    <button class="quiz-card-btn" data-filename="${encFilename}" data-notebookid="${encNotebookId}" data-relpath="${encRelPath}" onclick="openQuizModalByEl(this)" title="NotebookLM Quiz">🧩 Quiz</button>
                                    <button class="action-btn demote-btn" data-relpath="${encRelPath}" onclick="moveNoteByEl(this, 'inbox')" title="Demote to Inbox">📥 Demote to Inbox</button>
                                ` : p.category === 'incubator' ? `
                                    <button class="action-btn promote-btn" data-relpath="${encRelPath}" onclick="moveNoteByEl(this, 'inbox')" title="Move to Inbox">📥 Move to Inbox</button>
                                    <button class="action-btn promote-btn" data-relpath="${encRelPath}" onclick="moveNoteByEl(this, 'knowledge')" title="Promote to Knowledge">🎓 Promote to Knowledge</button>
                                ` : `
                                    ${playBtnHtml}
                                `}
                            </div>
                        </div>
                    </div>
                `;
            }).join('');
        }

        // Toggle Expandable Summaries
        window.toggleSummaryByEl = function(btnEl) {
            const filename = decodeURIComponent(btnEl.dataset.filename || '');
            window.toggleSummary(filename);
        };

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

        function getApiUrl(path) {
            const origin = window.location.origin && window.location.origin.startsWith('http') ? window.location.origin : 'http://localhost:8085';
            return origin + path;
        }

        // Floating Toast Notification System
        function showToast(msg, isError = false) {
            let toast = document.getElementById('app-toast');
            if (!toast) {
                toast = document.createElement('div');
                toast.id = 'app-toast';
                toast.style.cssText = 'position: fixed; bottom: 24px; right: 24px; z-index: 10000; padding: 12px 20px; border-radius: 10px; font-size: 0.9rem; font-weight: 600; color: #fff; box-shadow: 0 10px 25px rgba(0,0,0,0.5); transition: opacity 0.3s ease; pointer-events: none;';
                document.body.appendChild(toast);
            }
            toast.style.background = isError ? 'linear-gradient(135deg, #ef4444, #dc2626)' : 'linear-gradient(135deg, #6366f1, #8b5cf6)';
            toast.textContent = msg;
            toast.style.opacity = '1';
            setTimeout(() => { toast.style.opacity = '0'; }, 3500);
        }

        // Custom Confirmation Modal System
        let confirmPendingCallback = null;
        window.showConfirmModal = function(title, message, onConfirm) {
            document.getElementById('confirm-modal-title').textContent = title || 'Confirm Action';
            document.getElementById('confirm-modal-message').textContent = message || 'Are you sure?';
            confirmPendingCallback = onConfirm;
            document.getElementById('confirm-modal-overlay').classList.add('active');
        };
        window.closeConfirmModal = function() {
            document.getElementById('confirm-modal-overlay').classList.remove('active');
            confirmPendingCallback = null;
        };
        document.getElementById('confirm-modal-ok-btn').onclick = function() {
            const cb = confirmPendingCallback;
            closeConfirmModal();
            if (cb) cb();
        };

        // Custom Add Note Modal System
        let currentAddNoteRelPath = '';
        window.promptAddNoteByEl = function(btnEl) {
            const relPath = decodeURIComponent(btnEl.dataset.relpath || '');
            window.promptAddNote(relPath);
        };
        window.promptAddNote = function(relPath) {
            currentAddNoteRelPath = relPath;
            document.getElementById('note-text-input').value = '';
            document.getElementById('note-modal-overlay').classList.add('active');
            setTimeout(() => document.getElementById('note-text-input').focus(), 100);
        };
        window.closeNoteModal = function() {
            document.getElementById('note-modal-overlay').classList.remove('active');
            currentAddNoteRelPath = '';
        };
        document.getElementById('save-note-btn').onclick = async function() {
            const noteText = document.getElementById('note-text-input').value;
            if (!noteText || !noteText.trim()) {
                showToast('Please type a note before saving', true);
                return;
            }
            const relPath = currentAddNoteRelPath;
            closeNoteModal();
            try {
                const res = await fetch(getApiUrl('/api/add_note'), {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ note_path: relPath, text: noteText.trim() })
                });
                const data = await res.json();
                if (data.success) {
                    showToast('📝 Note appended successfully!');
                } else {
                    showToast('Error adding note: ' + (data.error || 'Failed'), true);
                }
            } catch(e) {
                showToast('Add note failed: ' + e.message, true);
            }
        };

        // Trigger NotebookLM Generation in Background
        window.triggerGenerateArtifact = async function(relPath, artifactType) {
            try {
                const res = await fetch(getApiUrl('/api/generate_artifact'), {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ note_path: relPath, artifact_type: artifactType })
                });
                const data = await res.json();
                showToast(data.message || `Started ${artifactType} generation in background!`);
            } catch(e) {
                showToast('Artifact generation failed: ' + e.message, true);
            }
        };

        window.moveNoteByEl = function(btnEl, destStage) {
            const relPath = decodeURIComponent(btnEl.dataset.relpath || '');
            window.moveNote(relPath, destStage);
        };

        // Move Note Stage API Handler
        window.moveNote = async function(relPath, destStage) {
            try {
                const res = await fetch(getApiUrl('/api/move_note'), {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ note_path: relPath, destination: destStage })
                });
                const data = await res.json();
                if (data.success) {
                    showToast(data.message);
                    const freshRes = await fetch(getApiUrl('/api/podcasts'));
                    allPodcasts = await freshRes.json();
                    renderPodcasts();
                } else {
                    showToast('Error moving note: ' + (data.error || 'Failed'), true);
                }
            } catch(e) {
                showToast('Move failed: ' + e.message, true);
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

        window.togglePlayPodcastByEl = function(btnEl) {
            const filename = decodeURIComponent(btnEl.dataset.filename || '');
            const relPath = decodeURIComponent(btnEl.dataset.relpath || '');
            window.togglePlayPodcast(filename, relPath);
        };

        // Toggle audio play/pause
        window.togglePlayPodcast = function(filename, relPath) {
            const podcast = allPodcasts.find(p => (filename && p.filename === filename) || (relPath && p.rel_path === relPath));
            if (podcast && podcast.filename) {
                if (currentPodcast && currentPodcast.filename === podcast.filename) {
                    if (audio.paused) {
                        audio.play();
                    } else {
                        audio.pause();
                    }
                } else {
                    currentPodcast = podcast;
                    audio.src = `/audio/${encodeURIComponent(podcast.filename)}`;
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
            } else {
                const targetPath = relPath || (podcast ? podcast.rel_path : '');
                showConfirmModal(
                    "🎙️ Generate Audio",
                    "No podcast audio generated yet for this note. Would you like to generate a podcast with NotebookLM now?",
                    () => window.triggerGenerateArtifact(targetPath, 'audio')
                );
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

        // NotebookLM Interactive Quiz State & Functions
        let currentQuizQuestions = [];
        let currentQuestionIdx = 0;
        let userAnswers = {};

        let quizPollTimer = null;

        window.openQuizModalByEl = function(btnEl) {
            const filename = decodeURIComponent(btnEl.dataset.filename || '');
            const notebookId = decodeURIComponent(btnEl.dataset.notebookid || '');
            const relPath = decodeURIComponent(btnEl.dataset.relpath || '');
            window.openQuizModal(filename, notebookId, relPath);
        };

        window.openQuizModal = function(filename, notebookId, notePath) {
            const overlay = document.getElementById('quiz-modal-overlay');
            const qText = document.getElementById('quiz-question-text');
            const optList = document.getElementById('quiz-options-list');
            
            overlay.classList.add('active');
            qText.innerHTML = `
                <div style="text-align: center; padding: 20px 10px;">
                    <div style="margin: 0 auto 16px auto; width: 36px; height: 36px; border: 3px solid rgba(255,255,255,0.1); border-top-color: #8b5cf6; border-radius: 50%; animation: spin 1s linear infinite;"></div>
                    <p style="margin:0; font-weight:500; font-size:1.05rem;">Fetching NotebookLM Quiz...</p>
                </div>
            `;
            optList.innerHTML = '';
            
            loadQuizData(notebookId, notePath);
        };

        async function loadQuizData(notebookId, notePath) {
            if (quizPollTimer) clearInterval(quizPollTimer);
            const targetUrl = getApiUrl(`/api/quiz?notebook_id=${encodeURIComponent(notebookId || '')}&note_path=${encodeURIComponent(notePath || '')}`);
            
            try {
                const res = await fetch(targetUrl);
                if (!res.ok) throw new Error("HTTP error " + res.status);
                const data = await res.json();
                
                if (data && data.questions && data.questions.length > 0) {
                    currentQuizQuestions = data.questions;
                    currentQuestionIdx = 0;
                    userAnswers = {};
                    renderQuizQuestion();
                } else if (data && data.error) {
                    renderQuizError(data.error);
                } else {
                    showConfirmModal(
                        "🧩 Generate Quiz",
                        "Quiz not yet generated for this note. Would you like to generate a Quiz with NotebookLM now?",
                        () => startQuizGenerationAndPoll(notebookId, notePath)
                    );
                }
            } catch(err) {
                console.error("Failed to load quiz:", err);
                renderQuizError("Unable to fetch quiz questions. Please check server connection.");
            }
        }

        function renderQuizError(errMsg) {
            const qText = document.getElementById('quiz-question-text');
            const optList = document.getElementById('quiz-options-list');
            document.getElementById('quiz-counter').textContent = 'Error';
            
            let icon = '⚠️';
            let title = 'Quiz Unavailable';
            if (errMsg.toLowerCase().includes('authenticated') || errMsg.toLowerCase().includes('login')) {
                icon = '🔒';
                title = 'NotebookLM Authentication Required';
            }

            qText.innerHTML = `
                <div style="text-align: center; padding: 20px 10px;">
                    <div style="font-size: 2.5rem; margin-bottom: 12px;">${icon}</div>
                    <h3 style="color: #ef4444; margin: 0 0 10px 0; font-size: 1.15rem;">${title}</h3>
                    <p style="color: var(--text-secondary); line-height: 1.5; font-size: 0.95rem; margin: 0;">${errMsg}</p>
                </div>
            `;
            optList.innerHTML = '';
        }

        function startQuizGenerationAndPoll(notebookId, notePath) {
            const overlay = document.getElementById('quiz-modal-overlay');
            const qText = document.getElementById('quiz-question-text');
            const optList = document.getElementById('quiz-options-list');
            
            overlay.classList.add('active');
            qText.innerHTML = `
                <div style="text-align: center; padding: 24px 10px;">
                    <div style="margin: 0 auto 16px auto; width: 40px; height: 40px; border: 4px solid rgba(255,255,255,0.1); border-top-color: #8b5cf6; border-radius: 50%; animation: spin 1s linear infinite;"></div>
                    <h4 style="margin: 0 0 8px 0; color: #fff; font-size: 1.1rem;">⏳ Generating NotebookLM Quiz in Background...</h4>
                    <p style="color: var(--text-secondary); font-size: 0.9rem; margin: 0;">This takes ~30–45 seconds. Auto-loading quiz as soon as it's ready.</p>
                </div>
            `;
            optList.innerHTML = '';
            
            window.triggerGenerateArtifact(notePath, 'quiz');
            
            let pollAttempts = 0;
            quizPollTimer = setInterval(async () => {
                pollAttempts++;
                const targetUrl = getApiUrl(`/api/quiz?notebook_id=${encodeURIComponent(notebookId || '')}&note_path=${encodeURIComponent(notePath || '')}`);
                try {
                    const res = await fetch(targetUrl);
                    const data = await res.json();
                    if (data && data.questions && data.questions.length > 0) {
                        clearInterval(quizPollTimer);
                        quizPollTimer = null;
                        currentQuizQuestions = data.questions;
                        currentQuestionIdx = 0;
                        userAnswers = {};
                        showToast('✨ Quiz generation complete!');
                        renderQuizQuestion();
                    } else if (data && data.error) {
                        clearInterval(quizPollTimer);
                        quizPollTimer = null;
                        renderQuizError(data.error);
                    } else if (pollAttempts > 25) {
                        clearInterval(quizPollTimer);
                        quizPollTimer = null;
                        renderQuizError("Quiz generation timed out. Please try again.");
                    }
                } catch(e) {}
            }, 4000);
        }

        window.closeQuizModal = function() {
            if (quizPollTimer) {
                clearInterval(quizPollTimer);
                quizPollTimer = null;
            }
            document.getElementById('quiz-modal-overlay').classList.remove('active');
        };

        function renderQuizQuestion() {
            if (currentQuestionIdx >= currentQuizQuestions.length) {
                renderQuizResults();
                return;
            }

            const q = currentQuizQuestions[currentQuestionIdx];
            document.getElementById('quiz-counter').textContent = `${currentQuestionIdx + 1} / ${currentQuizQuestions.length}`;
            document.getElementById('quiz-question-text').textContent = q.question;
            
            const hintBox = document.getElementById('quiz-hint-box');
            hintBox.style.display = 'none';
            hintBox.textContent = q.hint || "No hint available.";

            const optList = document.getElementById('quiz-options-list');
            const letters = ['A', 'B', 'C', 'D'];
            const options = q.options || q.answerOptions || [];
            
            optList.innerHTML = options.map((opt, i) => {
                const letter = letters[i] || `${i+1}`;
                const isCorrect = opt.correct !== undefined ? opt.correct : (opt.isCorrect !== undefined ? opt.isCorrect : false);
                const text = opt.text || opt.answer || '';
                return `
                    <button class="quiz-option-btn" onclick="selectQuizOption(${i}, ${isCorrect})">
                        <strong>${letter}.</strong> <span>${text}</span>
                    </button>
                `;
            }).join('');
            
            document.getElementById('quiz-next-btn').style.display = 'none';
        }

        window.selectQuizOption = function(optIdx, isCorrect) {
            userAnswers[currentQuestionIdx] = isCorrect;
            const buttons = document.querySelectorAll('.quiz-option-btn');
            
            buttons.forEach((btn, idx) => {
                btn.onclick = null;
                if (idx === optIdx) {
                    if (isCorrect) {
                        btn.classList.add('selected-correct');
                    } else {
                        btn.classList.add('selected-incorrect');
                    }
                }
            });
            
            document.getElementById('quiz-next-btn').style.display = 'block';
        };

        window.toggleQuizHint = function() {
            const hintBox = document.getElementById('quiz-hint-box');
            hintBox.style.display = hintBox.style.display === 'none' ? 'block' : 'none';
        };

        window.nextQuizQuestion = function() {
            currentQuestionIdx++;
            renderQuizQuestion();
        };

        function renderQuizResults() {
            const total = currentQuizQuestions.length;
            const correctCount = Object.values(userAnswers).filter(Boolean).length;
            const pct = Math.round((correctCount / total) * 100);

            document.getElementById('quiz-counter').textContent = "Completed";
            document.getElementById('quiz-question-text').textContent = `🎯 Quiz Score: ${pct}% (${correctCount}/${total} Correct)`;
            document.getElementById('quiz-options-list').innerHTML = `
                <p style="color: var(--text-secondary); line-height: 1.5;">
                    Your performance score of <strong>${pct}%</strong> has been recorded. Outstanding work testing active recall!
                </p>
            `;
            document.getElementById('quiz-next-btn').textContent = "Close";
            document.getElementById('quiz-next-btn').onclick = closeQuizModal;
        }

        // Check for URL query params to auto-open quiz modal on load
        const urlParams = new URLSearchParams(window.location.search);
        if (urlParams.get('quiz') === 'true') {
            const paramNotebookId = urlParams.get('notebook_id') || '';
            const paramNotePath = urlParams.get('note_path') || '';
            window.openQuizModal('Quiz', paramNotebookId, paramNotePath);
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
    try:
        with socketserver.TCPServer(("0.0.0.0", PORT), PodcastHTTPHandler) as httpd:
            try:
                httpd.serve_forever()
            except KeyboardInterrupt:
                print("\n[-] Shutting down podcast server.")
    except OSError as e:
        if getattr(e, 'winerror', None) == 10048 or "Address already in use" in str(e):
            print(f"[!] Server is already running on port {PORT}. Exiting duplicate process.")
        else:
            raise e

if __name__ == "__main__":
    main()
