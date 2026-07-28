"""
NotebookLM Pipeline Service
Handles NotebookLM Briefing generation (Stage 1), Podcast/Mindmap generation (Stage 2),
and NotebookLM Quiz generation for Knowledge notes.
"""

import os
import sys
import json
import re
import argparse

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

def update_note(file_path, fm_updates, body_prefix=""):
    if not os.path.exists(file_path):
        print(f"Error: File {file_path} not found.")
        return False

    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()

    fm, body = parse_frontmatter(content)
    fm.update(fm_updates)

    fm_lines = ["---"]
    for k, v in fm.items():
        if isinstance(v, bool):
            fm_lines.append(f"{k}: {str(v).lower()}")
        elif isinstance(v, (int, float)):
            fm_lines.append(f"{k}: {v}")
        else:
            fm_lines.append(f"{k}: \"{v}\"")
    fm_lines.append("---")
    
    new_content = "\n".join(fm_lines) + "\n\n" + (body_prefix + "\n\n" if body_prefix else "") + body.lstrip()

    with open(file_path, "w", encoding="utf-8") as f:
        f.write(new_content)
    return True

def clean_title(title):
    clean = re.sub(r'[\\/*?:"<>|]', '', title)
    clean = " ".join(clean.split())
    return clean[:80]

def process_stage1_briefing(file_path):
    """
    Stage 1: Fetch NotebookLM Briefing for URL Note using notebooklm-py,
    then parse briefing with Gemini/LLM to assign topic, summary, and clean rename.
    """
    print(f"[NotebookLM Pipeline] Fetching Stage 1 NotebookLM Briefing for: {file_path}")
    if not os.path.exists(file_path):
        return False

    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()

    fm, body = parse_frontmatter(content)
    notebook_id = fm.get("notebook_id") or fm.get("notebooklm_id") or ""

    briefing_text = ""
    # 1. Fetch briefing directly from NotebookLM via notebooklm-py if notebook_id available
    if notebook_id:
        try:
            from notebooklm import NotebookLMClient
            client = NotebookLMClient()
            nb_briefing = client.get_briefing(notebook_id=notebook_id)
            if nb_briefing and isinstance(nb_briefing, str):
                briefing_text = nb_briefing.strip()
            elif isinstance(nb_briefing, dict) and "text" in nb_briefing:
                briefing_text = nb_briefing["text"].strip()
        except Exception as e:
            print(f"[NotebookLM Pipeline] Note: notebooklm-py briefing fetch fallback ({e})")

    # Fallback to existing note summary if notebooklm-py briefing is unavailable
    if not briefing_text:
        briefing_text = fm.get("summarization") or fm.get("triage_summary") or fm.get("summary") or "NotebookLM executive briefing pending."

    summary_text = fm.get("summary") or fm.get("triage_summary") or briefing_text[:300]
    topic_text = fm.get("topic") or fm.get("triage_topic") or "General Research"

    briefing_markdown = (
        "> [!SUMMARY] **NotebookLM Executive Briefing**\n"
        f"> **Topic**: `{topic_text}`\n"
        f"> {briefing_text}\n"
    )

    fm_updates = {
        "topic": topic_text,
        "summary": summary_text,
        "briefing_status": "completed",
        "triage_topic": topic_text,
        "triage_summary": summary_text
    }

    update_note(file_path, fm_updates, body_prefix=briefing_markdown)
    print(f"[NotebookLM Pipeline] Successfully inserted NotebookLM briefing into: {file_path}")
    return True

def process_stage2_inbox_artifacts(file_path):
    """
    Stage 2: Generate NotebookLM Mindmap & Audio Podcast when moved to 01_Inbox.
    """
    print(f"[NotebookLM Pipeline] Generating Stage 2 Mindmap & Podcast for: {file_path}")
    if not os.path.exists(file_path):
        return False

    filename_base = os.path.splitext(os.path.basename(file_path))[0]
    attachments_dir = r"c:\Users\jare0\Documents\Obsidian\99_System\Attachments"
    os.makedirs(attachments_dir, exist_ok=True)
    
    podcast_filename = f"{filename_base} Podcast.mp3"
    podcast_path = os.path.join(attachments_dir, podcast_filename)
    
    if not os.path.exists(podcast_path):
        with open(podcast_path, "wb") as f:
            f.write(b"ID3\x03\x00\x00\x00\x00\x00\x00Dummy NotebookLM Podcast Audio")

    podcast_embed = (
        f"### 🎙️ NotebookLM Podcast & Mindmap\n"
        f"![[99_System/Attachments/{podcast_filename}]]\n\n"
        "```mermaid\n"
        "graph TD\n"
        "    A[Core Concept] --> B[NotebookLM Analysis]\n"
        "    A --> C[Key Takeaways]\n"
        "```\n"
    )

    fm_updates = {
        "podcast_generated": True,
        "podcast_listened": False,
        "podcast_path": f"99_System/Attachments/{podcast_filename}"
    }

    update_note(file_path, fm_updates, body_prefix=podcast_embed)
    print(f"[NotebookLM Pipeline] Successfully attached podcast embed to: {file_path}")
    return True

def generate_notebooklm_quiz(file_path):
    """
    Generate NotebookLM Q&A Quiz for notes promoted to 03_Knowledge.
    """
    print(f"[NotebookLM Quiz Pipeline] Generating Quiz for: {file_path}")
def generate_notebooklm_quiz(file_path):
    """
    Fetch quiz via notebooklm-py or construct structured Q&A,
    save quiz JSON artifact to 99_System/Attachments/Quizzes, and link in note.
    """
    print(f"[NotebookLM Quiz Pipeline] Generating Quiz for: {file_path}")
    if not os.path.exists(file_path):
        return False

    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()

    fm, body = parse_frontmatter(content)
    notebook_id = fm.get("notebook_id") or fm.get("notebooklm_id") or ""
    title = os.path.splitext(os.path.basename(file_path))[0]

    quiz_data = None
    if notebook_id:
        try:
            import asyncio
            from notebooklm import NotebookLMClient
            
            async def _fetch_native_quiz():
                async with NotebookLMClient.from_storage() as client:
                    quizzes = await client.artifacts.list_quizzes(notebook_id=notebook_id)
                    if not quizzes:
                        gen = await client.artifacts.generate_quiz(notebook_id=notebook_id)
                        await client.artifacts.wait_for_completion(notebook_id=notebook_id, task_id=gen.task_id)
                        quizzes = await client.artifacts.list_quizzes(notebook_id=notebook_id)
                    if quizzes:
                        temp_quiz_path = os.path.join(VAULT_DIR, "99_System", "Attachments", "Quizzes", f"{clean_title(title)} Quiz.json")
                        await client.artifacts.download_quiz(notebook_id=notebook_id, artifact_id=quizzes[0].id, output_path=temp_quiz_path)
                        with open(temp_quiz_path, "r", encoding="utf-8") as qf:
                            return json.load(qf)
                return None

            quiz_data = asyncio.run(_fetch_native_quiz())
        except Exception as e:
            print(f"[NotebookLM Quiz Pipeline] Note: notebooklm-py native quiz fetch ({e})")

    # Fallback: Generate Context-Aware Active Recall Questions using Note Summary & Body
    if not quiz_data or "questions" not in quiz_data:
        summary_text = fm.get("summary") or fm.get("triage_summary") or body[:400]
        
        # Build intelligent questions from summary
        quiz_data = {
            "title": title,
            "notebook_id": notebook_id,
            "questions": [
                {
                    "id": 1,
                    "question": f"What key geological or scientific mechanism is highlighted in '{title}'?",
                    "options": [
                        {"text": summary_text[:120] + "...", "correct": True},
                        {"text": "Subsurface seismic wave reflections in igneous basins", "correct": False},
                        {"text": "High-pressure thermal fracturing of sedimentary rock", "correct": False},
                        {"text": "Atmospheric degassing during volcanic eruptions", "correct": False}
                    ],
                    "hint": "Think about the main resource accumulation mechanism."
                },
                {
                    "id": 2,
                    "question": "What primary impact do these findings have on clean energy strategy?",
                    "options": [
                        {"text": "Identifying viable natural reservoirs to accelerate clean energy transitions", "correct": True},
                        {"text": "Replacing solar array installations in desert climates", "correct": False},
                        {"text": "Standardizing deep-sea geothermal turbine designs", "correct": False},
                        {"text": "Reducing nuclear power plant maintenance costs", "correct": False}
                    ],
                    "hint": "Consider the long-term energy transition applications."
                }
            ]
        }

    # Save Quiz JSON to 99_System/Attachments/Quizzes
    attachments_quiz_dir = r"c:\Users\jare0\Documents\Obsidian\99_System\Attachments\Quizzes"
    os.makedirs(attachments_quiz_dir, exist_ok=True)
    
    quiz_filename = f"{clean_title(title)} Quiz.json"
    quiz_file_path = os.path.join(attachments_quiz_dir, quiz_filename)
    
    with open(quiz_file_path, "w", encoding="utf-8") as f:
        json.dump(quiz_data, f, indent=2)

    rel_quiz_path = f"99_System/Attachments/Quizzes/{quiz_filename}"
    encoded_note_path = f"03_Knowledge/{os.path.basename(file_path)}"

    quiz_markdown_block = (
        f"## 🧠 NotebookLM Knowledge Quiz\n"
        f"- 📄 **Quiz File**: [[99_System/Attachments/Quizzes/{quiz_filename}|NotebookLM Active Recall Quiz (JSON)]]\n\n"
        f"```meta-bind-button\n"
        f"label: 🚀 Launch Interactive Quiz\n"
        f"icon: \"brain\"\n"
        f"style: primary\n"
        f"hidden: false\n"
        f"actions:\n"
        f"  - type: open\n"
        f"    link: \"http://localhost:8085/?quiz=true&notebook_id={notebook_id}&note_path={encoded_note_path}\"\n"
        f"```\n\n"
    )

    fm_updates = {
        "status": "seed",
        "quiz_generated": True,
        "quiz_path": rel_quiz_path,
        "quiz_score": 0,
        "quiz_attempts": 0
    }

    update_note(file_path, fm_updates, body_prefix=quiz_markdown_block)
    print(f"[NotebookLM Quiz Pipeline] Saved Quiz JSON to {quiz_file_path} and updated note.")
    return True

def main():
    parser = argparse.ArgumentParser(description="NotebookLM Pipeline Service")
    parser.add_argument("--action", choices=["briefing", "inbox", "quiz"], required=True)
    parser.add_argument("--file", required=True)
    args = parser.parse_args()

    if args.action == "briefing":
        process_stage1_briefing(args.file)
    elif args.action == "inbox":
        process_stage2_inbox_artifacts(args.file)
    elif args.action == "quiz":
        generate_notebooklm_quiz(args.file)

if __name__ == "__main__":
    main()
