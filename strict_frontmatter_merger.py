"""
Strict Frontmatter Merger
Finds any file containing split '---' frontmatter blocks, parses all key-value pairs,
merges them into a single line 1 YAML frontmatter block, and moves callout blocks into the note body.
"""

import os
import re
import sys

sys.stdout.reconfigure(encoding='utf-8')
VAULT_DIR = r"c:\Users\jare0\Documents\Obsidian"

def fix_split_file(file_path):
    try:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()

        if not content.startswith("---"):
            return

        # Check if more than two '---' exist in top 1500 chars
        parts = content.split("---")
        if len(parts) <= 3:
            return

        # We have a split frontmatter! Collect all key-value properties
        all_properties = {}
        body_text_parts = []

        for p in parts[1:]:
            p_strip = p.strip()
            lines = p_strip.splitlines()
            # If all lines look like key: value, collect properties
            is_kv_block = len(lines) > 0 and all(":" in l or l.startswith("#") for l in lines)
            if is_kv_block and len(all_properties) < 25:
                for l in lines:
                    if ":" in l:
                        k, v = l.split(":", 1)
                        k = k.strip()
                        v = v.strip().strip('"').strip("'")
                        all_properties[k] = v
            else:
                if p_strip:
                    body_text_parts.append(p_strip)

        if not all_properties:
            return

        # Reconstruct single clean frontmatter block
        fm_lines = ["---"]
        for k, v in all_properties.items():
            fm_lines.append(f'{k}: "{v}"')
        fm_lines.append("---")

        full_body = "\n\n".join(body_text_parts)
        # Extract callouts
        callouts = re.findall(r'(> \[!.*?\][\s\S]*?)(?=\n\n|\n[^\>]|$)', full_body)
        clean_body = re.sub(r'> \[!.*?\][\s\S]*?\n\n', '', full_body).strip()

        callout_str = "\n\n".join(callouts) + "\n\n" if callouts else ""
        new_content = "\n".join(fm_lines) + "\n\n" + callout_str + clean_body

        with open(file_path, "w", encoding="utf-8") as out:
            out.write(new_content)
        print(f"  [Merged Split Frontmatter] {os.path.basename(file_path)}")

    except Exception as e:
        print(f"Error processing {file_path}: {e}")

def run_strict_merger():
    print("[Strict Merger] Consolidating split frontmatter blocks...")
    for root, _, files in os.walk(VAULT_DIR):
        for f in files:
            if f.endswith(".md"):
                fix_split_file(os.path.join(root, f))

if __name__ == "__main__":
    run_strict_merger()
