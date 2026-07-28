"""
Vault Frontmatter Alignment & Callout Relocation Utility
Moves any callout blocks placed before YAML frontmatter to after the closing --- tag
so Obsidian parses line 1 YAML frontmatter properties properly across all folders.
"""

import os
import sys

VAULT_DIR = r"c:\Users\jare0\Documents\Obsidian"

def fix_file_frontmatter(file_path):
    try:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()

        # Check if callout exists before YAML frontmatter
        if content.startswith("> [!") and "\n---" in content:
            fm_start = content.find("\n---")
            fm_end = content.find("---", fm_start + 4)
            if fm_start != -1 and fm_end != -1:
                prefix_callout = content[:fm_start].strip()
                fm_block = content[fm_start + 1:fm_end + 3].strip()
                body_rest = content[fm_end + 3:].strip()

                fixed_content = f"{fm_block}\n\n{prefix_callout}\n\n{body_rest}"
                with open(file_path, "w", encoding="utf-8") as out:
                    out.write(fixed_content)
                print(f"Fixed Frontmatter Position: {file_path}")
    except Exception as e:
        print(f"Error processing {file_path}: {e}")

def run_vault_alignment():
    print("[Vault Alignment] Restoring line 1 YAML frontmatter across vault...")
    for root, _, files in os.walk(VAULT_DIR):
        for f in files:
            if f.endswith(".md"):
                fix_file_frontmatter(os.path.join(root, f))

if __name__ == "__main__":
    run_vault_alignment()
