"""
Subject-Matter Topic & Project Classifier V3
Separates Subject-Matter Content Topics (e.g. AI, Neuroscience, Quantum Physics, Psychology, Economics, Health)
from Target Project Destinations (Dynamical Representation Geometry, Quant, omni-logger, etc.).
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

def infer_content_topic(title, text):
    """Infer subject-matter content topic (Neuroscience, AI, Quantum Physics, Economics, etc.)."""
    comb = (title + " " + text).lower()
    
    if any(k in comb for k in ["brain", "neuroscience", "neuron", "synapse", "cortex", "hippocampus", "striatal", "ach", "mind"]):
        return "Neuroscience"
    elif any(k in comb for k in ["llm", "ai ", "agent", "deep learning", "machine learning", "neural network", "transformer", "model", "prompt"]):
        return "Artificial Intelligence"
    elif any(k in comb for k in ["quantum", "qubit", "entanglement", "physics", "gravity", "thermodynamics"]):
        return "Physics & Quantum"
    elif any(k in comb for k in ["stock", "trading", "sharpe", "cagr", "dividend", "portfolio", "finance", "market", "economy"]):
        return "Finance & Trading"
    elif any(k in comb for k in ["health", "meds", "sleep", "coffee", "exercise", "bicep", "pain", "lumosity"]):
        return "Health & Wellness"
    elif any(k in comb for k in ["math", "geometry", "topology", "manifold", "algebra", "theorem", "equation", "proof"]):
        return "Mathematics"
    elif any(k in comb for k in ["house", "gutter", "drainage", "mulch", "lawn", "hvac", "plumbing"]):
        return "Home & Maintenance"
    else:
        return "General Science"

def infer_target_project(title, text):
    """Infer target project folder in 04_Projects."""
    comb = (title + " " + text).lower()
    if any(k in comb for k in ["drg", "bmcid", "dynamical representation", "ruliad", "finsler", "theta", "manifold"]):
        return "Dynamical Representation Geometry"
    elif any(k in comb for k in ["quant", "backtest", "algorithmic trading", "trading strategy", "sharpe", "robinhood", "shadow portfolio", "cagr sp500"]):
        return "Quant"
    elif any(k in comb for k in ["puffco", "omni-logger", "ble_scan"]):
        return "omni-logger"
    elif any(k in comb for k in ["fitbit", "readiness score", "sleep_score"]):
        return "Cognitive Readiness Score"
    elif any(k in comb for k in ["podcast player hub", "notebooklm pipeline"]):
        return "knowledge-pipeline"
    elif any(k in comb for k in ["always-on", "memory agent"]):
        return "always-on-memory-agent"
    return "General Research"

def process_subject_matter_topics():
    print("[Topic System V3] Assigning subject-matter content topics and target projects...")
    
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
                title = fm.get("triage_title") or f.replace(".md", "")
                summary = fm.get("triage_summary") or fm.get("summary") or body[:500]

                # 1. Subject-Matter Content Topic (Neuroscience, AI, Finance, Physics, etc.)
                subject_topic = infer_content_topic(title, summary + " " + body[:1000])
                
                # 2. Target Project Destination (Quant, DRG, etc.)
                target_project = infer_target_project(title, summary + " " + body[:1000])

                fm["topic"] = subject_topic
                fm["content_topic"] = subject_topic
                fm["target_project"] = target_project
                fm["triage_topic"] = subject_topic

                briefing_block = f"> [!SUMMARY] **NotebookLM Executive Briefing**\n> **Topic**: `{subject_topic}` | **Project Target**: `{target_project}`\n> {summary}\n\n"

                fm_lines = ["---"]
                for k, v in fm.items():
                    fm_lines.append(f"{k}: \"{v}\"")
                fm_lines.append("---")

                clean_b = re.sub(r'> \[!SUMMARY\][\s\S]*?\n\n', '', body).lstrip()
                new_content = "\n".join(fm_lines) + "\n\n" + briefing_block + clean_b

                with open(file_path, "w", encoding="utf-8") as out_f:
                    out_f.write(new_content)
                print(f"  [Updated] {f} -> Content Topic: `{subject_topic}`, Target Project: `{target_project}`")

            except Exception as e:
                print(f"Error processing {f}: {e}")

if __name__ == "__main__":
    process_subject_matter_topics()
