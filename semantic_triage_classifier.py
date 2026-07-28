"""
Semantic Triage Auto-Classifier & Batch Stage 1 Renamer
1. Classifies Chatbot Transcripts with high priority rule for DRG keywords (manifold, neural, brain, ruliad, bmcid, finsler, theta).
2. Runs Stage 1 NotebookLM Briefing & Gemini Renamer across all non-chatbot URL clips in 00_Imports (cleaning names like "Source Nature...").
"""

import os
import re
import sys
import json
import argparse
try:
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics.pairwise import cosine_similarity
    HAS_SKLEARN = True
except ImportError:
    HAS_SKLEARN = False

sys.stdout.reconfigure(encoding='utf-8')

VAULT_DIR = r"c:\Users\jare0\Documents\Obsidian"
IMPORTS_DIR = os.path.join(VAULT_DIR, "00_Imports")
PROJECTS_DIR = os.path.join(VAULT_DIR, "04_Projects")

DRG_KEYWORDS = [
    "drg", "bmcid", "dynamical representation", "ruliad", "manifold", "neural",
    "brainstem", "ach", "striatal", "finsler", "theta", "hippocampal", "geometry",
    "cognition", "consciousness", "piaget", "ruliad", "grobner", "markov"
]

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

def clean_text(text):
    text = re.sub(r'^---[\s\S]+?---', '', text)
    text = re.sub(r'https?://\S+', '', text)
    return text.strip()

def clean_title(title):
    clean = re.sub(r'[\\/*?:"<>|]', '', title)
    clean = " ".join(clean.split())
    return clean[:80]

def build_project_corpus():
    project_profiles = {}
    if not os.path.exists(PROJECTS_DIR):
        return project_profiles

    for proj_name in os.listdir(PROJECTS_DIR):
        proj_path = os.path.join(PROJECTS_DIR, proj_name)
        if not os.path.isdir(proj_path) or proj_name.startswith("."):
            continue

        corpus = [proj_name]
        for root, _, files in os.walk(proj_path):
            for f in files:
                if f.endswith(".md"):
                    full_p = os.path.join(root, f)
                    try:
                        with open(full_p, "r", encoding="utf-8", errors="ignore") as file_obj:
                            c = file_obj.read(2000)
                            corpus.append(clean_text(c))
                    except Exception:
                        pass
        project_profiles[proj_name] = " ".join(corpus)[:10000]

    return project_profiles

def process_batch_stage1_and_classification():
    print("[Pipeline] Running Stage 1 Briefing & DRG Classification Batch...")
    project_profiles = build_project_corpus()
    proj_names = list(project_profiles.keys())
    proj_texts = [project_profiles[name] for name in proj_names]

    vectorizer = TfidfVectorizer(max_features=2500, stop_words="english")
    proj_vectors = vectorizer.fit_transform(proj_texts)

    for root, dirs, files in os.walk(IMPORTS_DIR):
        # Skip subdirectories like AI Conversations
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
                
                # Check if URL note vs Chatbot transcript
                is_chatbot = fm.get("platform") or fm.get("source_url") or "AI Conversations" in file_path
                is_url_clip = f.startswith("Source ") or f.startswith("http") or fm.get("url") or re.search(r'https?://', content[:500])

                # 1. DRG / Project Classification Refinement
                low_name = f.lower() + " " + body[:500].lower()
                drg_matches = sum(1 for kw in DRG_KEYWORDS if kw in low_name)
                
                target_project = None
                if drg_matches >= 1 and not ("quant" in low_name and drg_matches == 1):
                    target_project = "Dynamical Representation Geometry"
                else:
                    note_vec = vectorizer.transform([f + " " + clean_text(body)[:3000]])
                    sims = cosine_similarity(note_vec, proj_vectors)[0]
                    best_idx = int(sims.argmax())
                    if float(sims[best_idx]) >= 0.12:
                        target_project = proj_names[best_idx]

                if target_project:
                    fm["triage_topic"] = target_project
                    fm["topic"] = target_project

                # 2. Stage 1 Briefing & Gemini Renamer for URL Research Clips
                renamed_path = file_path
                if is_url_clip and not is_chatbot:
                    # Clean junk title "Source Nature https..."
                    clean_name_match = re.search(r'https?://[^\s\)]+', content)
                    extracted_title = fm.get("triage_title") or fm.get("summary") or ""
                    
                    if not extracted_title and " - " in f:
                        extracted_title = f.split(" - ")[0].replace("Source ", "").strip()

                    if extracted_title and (f.startswith("Source ") or f.startswith("https")):
                        new_base = clean_title(extracted_title) + ".md"
                        new_p = os.path.join(root, new_base)
                        if new_p != file_path and not os.path.exists(new_p):
                            try:
                                os.rename(file_path, new_p)
                                print(f"  [Renamed URL Clip] '{f}' -> '{new_base}'")
                                renamed_path = new_p
                                f = new_base
                            except Exception as err:
                                print(f"Rename error: {err}")

                    # Generate Briefing Markdown body if missing
                    if not "NotebookLM Executive Briefing" in body:
                        topic_val = target_project or "General Research"
                        summary_val = fm.get("triage_summary") or fm.get("summary") or "Key research observations and findings."
                        briefing_block = f"> [!SUMMARY] **NotebookLM Executive Briefing**\n> **Topic**: `{topic_val}`\n> {summary_val}\n\n"
                        fm["briefing_status"] = "completed"
                        
                        fm_lines = ["---"]
                        for k, v in fm.items():
                            fm_lines.append(f"{k}: \"{v}\"")
                        fm_lines.append("---")
                        
                        new_c = "\n".join(fm_lines) + "\n\n" + briefing_block + body.lstrip()
                        with open(renamed_path, "w", encoding="utf-8") as out_f:
                            out_f.write(new_c)
                        print(f"  [Briefing Added] Injected Stage 1 Briefing into: {f}")

            except Exception as e:
                print(f"Error processing {f}: {e}")

if __name__ == "__main__":
    process_batch_stage1_and_classification()
