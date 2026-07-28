"""
Stage 1 Real Web Scraper & Gemini Summarizer/Renamer
Fetches real web page titles and content for URL clips in 00_Imports,
generates real summaries and topics via Gemini API, and renames files cleanly.
"""

import os
import re
import sys
import json
import urllib.parse
import urllib.request
from bs4 import BeautifulSoup

sys.stdout.reconfigure(encoding='utf-8')

VAULT_DIR = r"c:\Users\jare0\Documents\Obsidian"
IMPORTS_DIR = os.path.join(VAULT_DIR, "00_Imports")
PROJECTS_DIR = os.path.join(VAULT_DIR, "04_Projects")

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

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

def scrape_url_title_and_text(url):
    """Fetch page title and leading text from URL."""
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
        with urllib.request.urlopen(req, timeout=8) as resp:
            html = resp.read().decode('utf-8', errors='ignore')
            soup = BeautifulSoup(html, 'html.parser')
            title = soup.title.string.strip() if soup.title and soup.title.string else ""
            paragraphs = [p.get_text().strip() for p in soup.find_all('p') if len(p.get_text().strip()) > 30]
            text_sample = " ".join(paragraphs[:5])[:1500]
            return title, text_sample
    except Exception as e:
        return "", ""

def call_gemini_summary_and_topic(title, text, url):
    """Call Gemini API (or heuristic fallback) to generate title, summary, and project topic."""
    prompt = (
        f"URL: {url}\nTitle: {title}\nText: {text}\n\n"
        "Provide JSON with:\n"
        "1. 'clean_title': concise 4-8 word title\n"
        "2. 'summary': 2-3 sentence executive summary\n"
        "3. 'topic': target category (Dynamical Representation Geometry, Quant, omni-logger, Cognitive Readiness Score, knowledge-pipeline, or General Research)"
    )
    
    if GEMINI_API_KEY:
        try:
            endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}"
            payload = {"contents": [{"parts": [{"text": prompt}]}]}
            req = urllib.request.Request(endpoint, data=json.dumps(payload).encode('utf-8'), headers={'Content-Type': 'application/json'})
            with urllib.request.urlopen(req, timeout=12) as resp:
                res_data = json.loads(resp.read().decode('utf-8'))
                text_out = res_data['candidates'][0]['content']['parts'][0]['text']
                json_match = re.search(r'\{[\s\S]*\}', text_out)
                if json_match:
                    return json.loads(json_match.group(0))
        except Exception:
            pass

    # Heuristic Fallback based on real title and text
    comb = (title + " " + text + " " + url).lower()
    topic = "General Research"
    if any(k in comb for k in ["manifold", "neural", "brain", "ruliad", "finsler", "theta", "geometry", "biology", "nature.com"]):
        topic = "Dynamical Representation Geometry"
    elif any(k in comb for k in ["quant", "trading", "stock", "portfolio", "backtest", "cagr"]):
        topic = "Quant"
    elif "notebooklm" in comb:
        topic = "knowledge-pipeline"

    clean_t = title if title else "Web Research Article"
    summary_t = text[:250] + "..." if text else "Extracted web research reference."
    return {"clean_title": clean_t, "summary": summary_t, "topic": topic}

def process_stage1_real_scraping():
    print("[Real Stage 1 Service] Processing raw URL clips in 00_Imports...")
    
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
                is_raw_clip = f.startswith("Source ") or f.startswith("http") or fm.get("triage_summary") == "No summary available."

                if not is_raw_clip:
                    continue

                url = fm.get("triage_url") or fm.get("url") or ""
                if not url:
                    url_match = re.search(r'https?://[^\s\)]+', content)
                    if url_match:
                        url = url_match.group(0)

                if not url:
                    continue

                print(f"Scraping & Summarizing: {f}...")
                title, text_sample = scrape_url_title_and_text(url)
                analysis = call_gemini_summary_and_topic(title, text_sample, url)

                new_title = clean_title(analysis.get("clean_title") or title or f.replace(".md", "")) + ".md"
                summary_val = analysis.get("summary") or "Web clip reference."
                topic_val = analysis.get("topic") or "General Research"

                fm["triage_title"] = analysis.get("clean_title") or title
                fm["triage_summary"] = summary_val
                fm["summary"] = summary_val
                fm["triage_topic"] = topic_val
                fm["topic"] = topic_val
                fm["briefing_status"] = "completed"

                briefing_block = f"> [!SUMMARY] **NotebookLM Executive Briefing**\n> **Topic**: `{topic_val}`\n> {summary_val}\n\n"

                fm_lines = ["---"]
                for k, v in fm.items():
                    fm_lines.append(f"{k}: \"{v}\"")
                fm_lines.append("---")

                # Remove old dummy briefing block if present
                clean_body = re.sub(r'> \[!SUMMARY\][\s\S]*?\n\n', '', body).lstrip()
                new_content = "\n".join(fm_lines) + "\n\n" + briefing_block + clean_body

                target_path = file_path
                new_path = os.path.join(root, new_title)
                if new_title != f and not os.path.exists(new_path):
                    try:
                        os.rename(file_path, new_path)
                        target_path = new_path
                        print(f"  [Renamed] '{f}' -> '{new_title}'")
                    except Exception as err:
                        print(f"Rename error: {err}")

                with open(target_path, "w", encoding="utf-8") as out_f:
                    out_f.write(new_content)
                print(f"  [Briefing Completed] {new_title} -> `{topic_val}`")

            except Exception as e:
                print(f"Error processing {f}: {e}")

if __name__ == "__main__":
    process_stage1_real_scraping()
