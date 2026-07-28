"""
Vault-wide Split Frontmatter Consolidator
Scans for markdown notes where frontmatter was split into two blocks
(e.g., block 1 -> briefing callout -> block 2) and merges all frontmatter key-values back
into a single, clean YAML frontmatter block starting strictly at line 1.
"""

import os
import re
import sys

sys.stdout.reconfigure(encoding='utf-8')

VAULT_DIR = r"c:\Users\jare0\Documents\Obsidian"

def fix_split_frontmatter(file_path):
    try:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()

        # Check if multiple --- separators exist
        dashes_count = content.count("\n---") + (1 if content.startswith("---") else 0)
        if dashes_count < 3 or not content.startswith("---"):
            return

        # Regex match all --- blocks in top 2000 chars
        blocks = content.split("---")
        if len(blocks) < 4:
            return

        # Extract all key-values across split frontmatter blocks
        combined_fm = {}
        non_fm_parts = []

        for idx, block in enumerate(blocks):
            lines = [l.strip() for l in block.strip().split("\n") if l.strip()]
            is_fm_candidate = all(":" in l or l.startswith("#") for l in lines) and len(lines) > 0
            
            if is_fm_candidate and idx < 4:
                for l in lines:
                    if ":" in l:
                        k, v = l.split(":", 1)
                        k = k.strip()
                        v = v.strip().strip('"').strip("'")
                        combined_fm[k] = v
            else:
                if block.strip():
                    non_fm_parts.append(block.strip())

        if not combined_fm:
            return

        # Reconstruct single clean frontmatter block
        fm_lines = ["---"]
        for k, v in combined_fm.items():
            fm_lines.append(f'{k}: "{v}"')
        fm_lines.append("---")

        body_text = "\n\n".join(non_fm_parts)
        # Separate callout blocks if found
        callouts = re.findall(r'(> \[!.*?\][\s\S]*?)(?=\n\n|\n[^\>]|$)', body_text)
        clean_body = re.sub(r'> \[!.*?\][\s\S]*?\n\n', '', body_text).strip()

        callout_str = "\n\n".join(callouts) + "\n\n" if callouts else ""
        new_content = "\n".join(fm_lines) + "\n\n" + callout_str + clean_body

        with open(file_path, "w", encoding="utf-8") as out:
            out.write(new_content)
        print(f"  [Consolidated Frontmatter] {file_path}")

    except Exception as e:
        print(f"Error processing {file_path}: {e}")

def run_split_frontmatter_sweep():
    print("[Consolidator] Sweeping vault to merge split frontmatter blocks into line 1...")
    for root, _, files in os.walk(VAULT_DIR):
        for f in files:
            if f.endswith(".md"):
                fix_split_frontmatter(os.path.join(root, f))

if __name__ == "__main__":
    run_split_frontmatter_sweep()
