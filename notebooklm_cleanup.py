import os
import re
import sys
import json
import subprocess

def run_cli_cmd(args):
    # Resolve absolute path to notebooklm.exe inside virtual environment
    if isinstance(args, str) and args.startswith("notebooklm "):
        venv_dir = os.path.dirname(sys.executable)
        notebooklm_bin = os.path.join(venv_dir, "notebooklm.exe" if os.name == "nt" else "notebooklm")
        if os.path.exists(notebooklm_bin):
            args = args.replace("notebooklm ", f'"{notebooklm_bin}" ', 1)

    try:
        res = subprocess.run(
            args,
            capture_output=True,
            text=True,
            shell=True,
            check=True
        )
        return res.stdout
    except Exception as e:
        return None

def main():
    vault_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    
    # 1. Scan vault for active notebooks
    vault_notes = []
    for root, dirs, files in os.walk(vault_dir):
        # Skip system or hidden dirs
        if ".obsidian" in root or ".git" in root:
            continue
        for file in files:
            if file.endswith(".md"):
                path = os.path.join(root, file)
                try:
                    with open(path, "r", encoding="utf-8", errors="ignore") as f:
                        content = f.read()
                    match = re.search(r'notebook_id:\s*["\']?([a-zA-Z0-9_-]+)', content)
                    if match:
                        notebook_id = match.group(1).strip()
                        # Check artifacts
                        has_mind_map = "## 🧠 Mind Map Diagram" in content or "mindmap" in content
                        has_podcast = "Podcast.mp3" in content or ("Podcast Audio" in content and "![[" in content)
                        has_video = "Video.mp4" in content or ("Cinematic Video" in content and "![[" in content)
                        
                        missing = []
                        if not has_mind_map:
                            missing.append("mind-map")
                        if not has_podcast:
                            missing.append("audio")
                        if not has_video:
                            missing.append("cinematic-video")
                            
                        vault_notes.append({
                            "notebook_id": notebook_id,
                            "file_path": path,
                            "relative_path": os.path.relpath(path, vault_dir),
                            "title": os.path.splitext(file)[0],
                            "missing": missing
                        })
                except Exception:
                    pass
                    
    # 2. Get all notebooks from NotebookLM CLI
    list_out = run_cli_cmd('notebooklm list --json')
    if not list_out:
        print(json.dumps({"error": "Failed to list notebooks from CLI. Check auth."}))
        sys.exit(1)
        
    try:
        list_data = json.loads(list_out)
        notebooks = list_data.get("notebooks", [])
    except Exception as e:
        print(json.dumps({"error": f"Failed to parse notebook list: {str(e)}"}))
        sys.exit(1)
        
    notebooks_map = {nb["id"]: nb for nb in notebooks}
    
    # 3. Analyze each active notebook in the vault
    cleanable = []
    missing_artifacts = []
    others = []
    
    # Store vault notebook IDs
    vault_nb_ids = {vn["notebook_id"] for vn in vault_notes}
    
    for vn in vault_notes:
        nb_id = vn["notebook_id"]
        if nb_id not in notebooks_map:
            others.append({
                "notebook_id": nb_id,
                "title": vn["title"],
                "file_path": vn["file_path"],
                "relative_path": vn["relative_path"],
                "reason": "Notebook ID not found on Google (already deleted or different account)"
            })
            continue
            
        nb = notebooks_map[nb_id]
        
        # Check source count
        src_out = run_cli_cmd(f'notebooklm source list -n {nb_id} --json')
        source_count = 0
        if src_out:
            try:
                src_data = json.loads(src_out)
                source_count = src_data.get("count", 0)
            except Exception:
                pass
                
        if source_count > 1:
            others.append({
                "notebook_id": nb_id,
                "title": nb["title"],
                "file_path": vn["file_path"],
                "relative_path": vn["relative_path"],
                "reason": f"Notebook has multiple sources ({source_count})"
            })
            continue
            
        # Single source check
        if len(vn["missing"]) == 0:
            cleanable.append({
                "notebook_id": nb_id,
                "title": nb["title"],
                "file_path": vn["file_path"],
                "relative_path": vn["relative_path"]
            })
        else:
            missing_artifacts.append({
                "notebook_id": nb_id,
                "title": nb["title"],
                "file_path": vn["file_path"],
                "relative_path": vn["relative_path"],
                "missing": vn["missing"]
            })
            
    # Include notebooks that are on Google but not referenced in the vault
    for nb in notebooks:
        nb_id = nb["id"]
        if nb_id not in vault_nb_ids:
            others.append({
                "notebook_id": nb_id,
                "title": nb["title"],
                "reason": "Not referenced in the vault"
            })
            
    report = {
        "cleanable": cleanable,
        "missing_artifacts": missing_artifacts,
        "others": others
    }
    print(json.dumps(report, indent=2))

if __name__ == "__main__":
    main()
