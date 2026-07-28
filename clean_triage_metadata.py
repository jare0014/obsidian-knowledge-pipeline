"""
Triage Metadata Cleanup Utility
Cleans out transient triage_* frontmatter properties (triage_title, triage_summary, triage_topic, triage_url, etc.)
from notes already sitting in 01_Incubator, 01_Inbox, 03_Knowledge, and 99_Archive.
"""

import os

VAULT_DIR = r"c:\Users\jare0\Documents\Obsidian"
CLEAN_TARGET_DIRS = ["01_Incubator", "01_Inbox", "03_Knowledge", "99_Archive"]

def clean_file_triage_metadata(file_path):
    try:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()

        if not content.startswith("---"):
            return

        parts = content.split("---", 2)
        if len(parts) < 3:
            return

        fm_text = parts[1]
        body = parts[2]
        lines = fm_text.strip().split("\n")
        
        new_lines = []
        changed = False
        for l in lines:
            if any(l.strip().startswith(prefix) for prefix in [
                "triage_title:", "triage_summary:", "triage_topic:",
                "triage_url:", "triage_category:", "triage_classified:",
                "triage_suggested_path:"
            ]):
                changed = True
            else:
                new_lines.append(l)

        if changed:
            new_fm = "---\n" + "\n".join(new_lines) + "\n---"
            new_content = new_fm + body
            with open(file_path, "w", encoding="utf-8") as out:
                out.write(new_content)
            print(f"  [Cleaned Triage Properties] {os.path.basename(file_path)}")

    except Exception as e:
        print(f"Error cleaning {file_path}: {e}")

def run_triage_cleanup_sweep():
    print("[Triage Cleanup] Removing transient triage_* frontmatter from promoted notes...")
    for target in CLEAN_TARGET_DIRS:
        target_dir = os.path.join(VAULT_DIR, target)
        if os.path.exists(target_dir):
            for root, _, files in os.walk(target_dir):
                for f in files:
                    if f.endswith(".md"):
                        clean_file_triage_metadata(os.path.join(root, f))

if __name__ == "__main__":
    run_triage_cleanup_sweep()
