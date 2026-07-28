"""
Return Knowledge Notes with Podcasts back to 00_Imports
Scans 03_Knowledge and moves any note that has an associated podcast file in 99_System/Attachments back into 00_Imports so it can go through Stage 1 Briefing processing.
"""

import os
import re

KNOWLEDGE_DIR = r"c:\Users\jare0\Documents\Obsidian\03_Knowledge"
IMPORTS_DIR = r"c:\Users\jare0\Documents\Obsidian\00_Imports"
ATTACHMENTS_DIR = r"c:\Users\jare0\Documents\Obsidian\99_System\Attachments"

def normalize(name):
    return re.sub(r'\s+', ' ', name.lower().replace(" podcast", "").replace(".mp3", "").strip())

def main():
    if not os.path.exists(ATTACHMENTS_DIR):
        print("Attachments dir not found.")
        return

    podcast_files = [f for f in os.listdir(ATTACHMENTS_DIR) if f.endswith("Podcast.mp3")]
    podcast_bases = {normalize(f): f for f in podcast_files}

    knowledge_files = [f for f in os.listdir(KNOWLEDGE_DIR) if f.endswith(".md")]
    
    moved_count = 0
    for kfile in knowledge_files:
        kpath = os.path.join(KNOWLEDGE_DIR, kfile)
        norm_kbase = normalize(kfile.replace(".md", ""))
        
        # Check if note has frontmatter podcast link or matching podcast file
        has_podcast = False
        with open(kpath, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
            if "Podcast.mp3" in content or "podcast_path" in content:
                has_podcast = True

        if not has_podcast:
            # Check attachment base match
            if norm_kbase in podcast_bases or any(norm_kbase in pb for pb in podcast_bases):
                has_podcast = True

        if has_podcast:
            target_path = os.path.join(IMPORTS_DIR, kfile)
            if not os.path.exists(target_path):
                os.rename(kpath, target_path)
                print(f"Moved back to Imports: {kfile}")
                moved_count += 1

    print(f"\nDone! Moved {moved_count} knowledge notes back to 00_Imports.")

if __name__ == "__main__":
    main()
