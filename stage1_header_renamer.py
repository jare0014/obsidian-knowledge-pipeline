"""
Stage 1 Scraper & Note Header Renamer V2
Reads note headers (# Title), frontmatter `summarization`, and body text inside markdown files
to accurately restore clean article titles, valid executive summaries, and correct project topics.
"""

import os
import re
import sys

sys.stdout.reconfigure(encoding='utf-8')

VAULT_DIR = r"c:\Users\jare0\Documents\Obsidian"
IMPORTS_DIR = os.path.join(VAULT_DIR, "00_Imports")

def parse_frontmatter(content):
    if content.startswith("---"):
        parts = content.split("---", 2)
        if len(parts) >= 3:
            fm_text = parts[1]
            body = parts[2]
            fm = {}
            for line in fm_text.strip().split("\n"):
                if ":" in line:
                    key, val = line.split(":", 1)
                    key = key.strip()
                    val = val.strip().strip('"').strip("'")
                    fm[key] = val
            return fm, body
    return {}, content

def clean_title(title):
    clean = re.sub(r'[\\/*?:"<>|]', '', title)
    clean = " ".join(clean.split())
    return clean[:80]

def process_stage1_header_renamer():
    print("[Stage 1 Renamer V2] Processing notes in 00_Imports...")
    
    for root, _, files in os.walk(IMPORTS_DIR):
        if "AI Conversations" in root:
            continue

        for f in files:
            if not f.endswith(".md") or f == "00_Triage_Console.md":
                continue

            file_path = os.path.join(root, f)
            try:
                with open(file_path, "r", encoding="utf-8", errors="ignore") as file_obj:
                    content = file_obj.read()

                fm, body = parse_frontmatter(content)
                
                # 1. Extract Real Title from Markdown Header `# Title` or `triage_suggested_path`
                real_title = ""
                header_match = re.search(r'^#\s+(.*?)(?:\s*\|.*)?$', body, re.MULTILINE)
                if header_match:
                    real_title = header_match.group(1).strip()
                elif fm.get("triage_suggested_path"):
                    path_base = os.path.basename(fm["triage_suggested_path"]).replace(".md", "")
                    if not path_base.startswith("Source"):
                        real_title = path_base

                if not real_title:
                    real_title = fm.get("triage_title") or f.replace(".md", "")

                # 2. Extract Real Summary (checking frontmatter summarization/summary/body)
                real_summary = fm.get("summarization") or fm.get("summary") or ""
                if not real_summary or "JavaScript" in real_summary:
                    summary_match = re.search(r'## 📝 Summarization\s*\n\s*(.*?)(?=\n\n|\n#|$)', body, re.DOTALL)
                    if summary_match:
                        real_summary = summary_match.group(1).strip()

                if not real_summary or "JavaScript" in real_summary:
                    # Clean body snippet fallback
                    clean_body = re.sub(r'> \[!SUMMARY\][\s\S]*?\n\n', '', body)
                    clean_body = re.sub(r'```[\s\S]*?```', '', clean_body)
                    clean_body = re.sub(r'#+\s+.*', '', clean_body).strip()
                    lines = [l.strip() for l in clean_body.split('\n') if len(l.strip()) > 30 and not l.startswith("Original Source") and not l.startswith("Source:")]
                    real_summary = " ".join(lines[:3])[:300] if lines else "Key research findings and notes."

                # 3. Classify Project Topic
                comb = (real_title + " " + real_summary + " " + f).lower()
                topic = "General Research"
                if any(k in comb for k in ["drg", "bmcid", "manifold", "neural", "brain", "ruliad", "finsler", "theta", "geometry", "biology", "nature.com", "cell"]):
                    topic = "Dynamical Representation Geometry"
                elif any(k in comb for k in ["quant", "trading", "stock", "portfolio", "backtest", "cagr", "sp500", "sharpe"]):
                    topic = "Quant"
                elif any(k in comb for k in ["notebooklm", "podcast"]):
                    topic = "knowledge-pipeline"
                elif any(k in comb for k in ["memory", "always-on"]):
                    topic = "always-on-memory-agent"

                # Update Frontmatter & Executive Briefing Body Block
                fm["triage_title"] = real_title
                fm["triage_summary"] = real_summary
                fm["summary"] = real_summary
                fm["triage_topic"] = topic
                fm["topic"] = topic
                fm["briefing_status"] = "completed"

                briefing_block = f"> [!SUMMARY] **NotebookLM Executive Briefing**\n> **Topic**: `{topic}`\n> {real_summary}\n\n"

                fm_lines = ["---"]
                for k, v in fm.items():
                    fm_lines.append(f"{k}: \"{v}\"")
                fm_lines.append("---")

                clean_b = re.sub(r'> \[!SUMMARY\][\s\S]*?\n\n', '', body).lstrip()
                new_content = "\n".join(fm_lines) + "\n\n" + briefing_block + clean_b

                # Clean Rename
                clean_name = clean_title(real_title) + ".md"
                target_path = file_path
                new_p = os.path.join(root, clean_name)
                
                if clean_name != f and not os.path.exists(new_p):
                    try:
                        os.rename(file_path, new_p)
                        target_path = new_p
                        print(f"  [Renamed] '{f}' -> '{clean_name}'")
                    except Exception as err:
                        print(f"Rename error: {err}")

                with open(target_path, "w", encoding="utf-8") as out_f:
                    out_f.write(new_content)
                print(f"  [Briefing Updated] {clean_name} -> `{topic}`")

            except Exception as e:
                print(f"Error processing {f}: {e}")

if __name__ == "__main__":
    process_stage1_header_renamer()
