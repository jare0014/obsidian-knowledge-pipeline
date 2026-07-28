import os
import re
import sys
import json
import glob
import shutil
import subprocess

vault_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
ATTACHMENTS_DIR = os.path.join(vault_dir, "99_System", "Attachments")
PODCASTS_DIR = os.path.join(ATTACHMENTS_DIR, "Podcasts")
IMPORTS_DIR = os.path.join(vault_dir, "00_Imports")
INBOX_DIR = os.path.join(vault_dir, "01_Inbox")
INCUBATOR_DIR = os.path.join(vault_dir, "01_Incubator")
KNOWLEDGE_DIR = os.path.join(vault_dir, "03_Knowledge")

def get_notebooklm_bin():
    venv_bin = os.path.join(os.path.dirname(sys.executable), "notebooklm.exe" if os.name == "nt" else "notebooklm")
    if os.path.exists(venv_bin):
        return f'"{venv_bin}"'
    return "notebooklm"

def run_notebooklm_cmd(cmd_str):
    bin_path = get_notebooklm_bin()
    if cmd_str.startswith("notebooklm "):
        cmd_str = cmd_str.replace("notebooklm ", f"{bin_path} ", 1)
    try:
        res = subprocess.run(cmd_str, capture_output=True, text=True, shell=True, timeout=120)
        return res.stdout
    except Exception as e:
        print(f"[Pipeline Linker] NotebookLM CLI call failed: {e}")
        return ""

def normalize_name(name):
    name = re.sub(r'Podcast(\s*\(\d+\))?\.mp3$', '', name, flags=re.IGNORECASE).strip()
    name = re.sub(r'\.(mp3|m4a|wav|ogg|flac|aac)$', '', name, flags=re.IGNORECASE).strip()
    name = re.sub(r'^\d{4}[-_]\d{2}[-_]\d{2}\s*', '', name).strip()
    return re.sub(r'\s+', ' ', name.lower().replace("_", " ").replace("-", " ")).strip()

def run_link_and_clean():
    print("[Pipeline Linker] Starting podcast linking, briefing generation, and vault sanitation...")
    
    # 1. Fetch briefings for notes in 00_Imports missing briefings
    if os.path.exists(IMPORTS_DIR):
        for file in os.listdir(IMPORTS_DIR):
            if not file.endswith(".md") or file == "00_Triage_Console.md":
                continue
                
            note_path = os.path.join(IMPORTS_DIR, file)
            with open(note_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
                
            has_briefing = "Executive Briefing" in content or "triage_summary" in content
            
            # Extract URL if present
            url_match = re.search(r'url:\s*["\']?(https?://[^\s"\']+)', content, re.IGNORECASE)
            if not url_match:
                url_match = re.search(r'(https?://[^\s\)"]+)', content)
                
            if not has_briefing and url_match:
                url = url_match.group(1).rstrip('>').rstrip(')')
                print(f"[Pipeline Linker] Fetching NotebookLM Briefing for: {file} ({url})...")
                
                try:
                    out = run_notebooklm_cmd(f'notebooklm create --url "{url}"')
                    notebook_id = ""
                    nb_match = re.search(r'([a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12})', out, re.IGNORECASE)
                    if nb_match:
                        notebook_id = nb_match.group(1)
                        
                    if notebook_id:
                        summary_out = run_notebooklm_cmd(f'notebooklm summary "{notebook_id}"')
                        if summary_out and len(summary_out.strip()) > 30:
                            briefing_block = f"\n\n> [!SUMMARY] **NotebookLM Executive Briefing**\n> {summary_out.strip()}\n"
                            landing_zones = "\n\n## 🎧 Podcast Audio & Artifacts\n<!-- START_PODCAST_LANDING_ZONE -->\n<!-- END_PODCAST_LANDING_ZONE -->\n\n## 🧠 Mind Map & Key Takeaways\n<!-- START_MINDMAP_LANDING_ZONE -->\n<!-- END_MINDMAP_LANDING_ZONE -->\n\n## 📝 Personal Notes & Highlights\n"
                            
                            # Add notebook_id to frontmatter
                            if content.startswith("---"):
                                content = content.replace("---", f"---\nnotebook_id: \"{notebook_id}\"", 1)
                            else:
                                content = f"---\nnotebook_id: \"{notebook_id}\"\n---\n" + content
                                
                            content += briefing_block + landing_zones
                            with open(note_path, "w", encoding="utf-8") as f:
                                f.write(content)
                            print(f"[Pipeline Linker] Successfully attached Briefing & Notebook ID to {file}")
                except Exception as e:
                    print(f"[Pipeline Linker] Failed briefing generation for {file}: {e}")

    # 2. Collect all audio assets across vault
    audio_files = []
    AUDIO_EXT = ('.mp3', '.m4a', '.wav', '.ogg', '.flac')
    
    for root, dirs, files in os.walk(vault_dir):
        dirs[:] = [d for d in dirs if not d.startswith(".") and d not in ("venv", ".venv", "node_modules", ".trash")]
        for f in files:
            if f.lower().endswith(AUDIO_EXT):
                audio_files.append(os.path.join(root, f))
                
    print(f"[Pipeline Linker] Found {len(audio_files)} audio asset(s) in vault.")
    
    # Index audio assets by normalized base name
    audio_map = {}
    for a_path in audio_files:
        filename = os.path.basename(a_path)
        norm = normalize_name(filename)
        if norm and norm not in audio_map:
            audio_map[norm] = a_path

    # 3. Collect all markdown notes across stage folders
    stage_folders = [IMPORTS_DIR, INBOX_DIR, INCUBATOR_DIR, KNOWLEDGE_DIR]
    linked_count = 0
    moved_to_inbox_count = 0
    
    for folder in stage_folders:
        if not os.path.exists(folder):
            continue
            
        for file in os.listdir(folder):
            if not file.endswith(".md") or file == "00_Triage_Console.md":
                continue
                
            note_path = os.path.join(folder, file)
            note_basename = os.path.splitext(file)[0]
            norm_note = normalize_name(note_basename)
            
            with open(note_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
                
            # Check if matching audio asset exists
            matched_audio = None
            if norm_note in audio_map:
                matched_audio = audio_map[norm_note]
            else:
                for norm_a, a_p in audio_map.items():
                    if len(norm_a) >= 8 and (norm_a in norm_note or norm_note in norm_a):
                        matched_audio = a_p
                        break
                        
            if matched_audio:
                audio_filename = os.path.basename(matched_audio)
                
                # Check if audio embed is missing in note landing zone
                if audio_filename not in content and "Podcast.mp3" not in content and ".mp3" not in content:
                    embed_block = f"\n\n## 🎧 Podcast Audio & Artifacts\n<!-- START_PODCAST_LANDING_ZONE -->\n![[{audio_filename}]]\n<!-- END_PODCAST_LANDING_ZONE -->\n"
                    if "<!-- START_PODCAST_LANDING_ZONE -->" in content:
                        content = re.sub(
                            r'<!-- START_PODCAST_LANDING_ZONE -->[\s\S]*?<!-- END_PODCAST_LANDING_ZONE -->',
                            f'<!-- START_PODCAST_LANDING_ZONE -->\n![[{audio_filename}]]\n<!-- END_PODCAST_LANDING_ZONE -->',
                            content
                        )
                    else:
                        content += embed_block
                        
                    with open(note_path, "w", encoding="utf-8") as f:
                        f.write(content)
                    linked_count += 1
                    print(f"[Pipeline Linker] Linked {audio_filename} into {file}")

                # Rule: Any note in 00_Imports that ALREADY has a podcast audio file is moved to 01_Inbox!
                if folder == IMPORTS_DIR:
                    if not os.path.exists(INBOX_DIR):
                        os.makedirs(INBOX_DIR)
                    dest_inbox_path = os.path.join(INBOX_DIR, file)
                    shutil.move(note_path, dest_inbox_path)
                    moved_to_inbox_count += 1
                    print(f"[Pipeline Linker] Promoted {file} with existing podcast from Imports -> 01_Inbox")

    print(f"[Pipeline Linker] Sanitation complete! Linked {linked_count} notes, moved {moved_to_inbox_count} notes with existing podcasts to 01_Inbox.")

if __name__ == "__main__":
    run_link_and_clean()
