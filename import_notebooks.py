import os
import re
import sys
import json
import difflib
import subprocess

def run_cli_cmd(args):
    try:
        res = subprocess.run(
            args,
            capture_output=True,
            text=True,
            shell=True,
            check=True
        )
        return res.stdout
    except subprocess.CalledProcessError as e:
        return e.stdout or e.stderr
    except Exception as e:
        return None

def normalize_title(title):
    return re.sub(r'[^a-zA-Z0-9\s]', '', title).lower().strip()

def main():
    if len(sys.argv) < 2:
        print(json.dumps({"error": "Vault path argument is required."}))
        sys.exit(1)

    vault_dir = sys.argv[1]
    
    if not os.path.isdir(vault_dir):
        print(json.dumps({"error": f"Invalid vault path: {vault_dir}"}))
        sys.exit(1)

    # 1. Scan vault for existing notebooks
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
                    
                    title = os.path.splitext(file)[0]
                    
                    # Extract notebook_id
                    notebook_id = None
                    match = re.search(r'notebook_id:\s*["\']?([a-zA-Z0-9_-]+)', content)
                    if match:
                        notebook_id = match.group(1).strip()
                        
                    vault_notes.append({
                        "notebook_id": notebook_id,
                        "title": title,
                        "normalized_title": normalize_title(title),
                        "file_path": path
                    })
                except Exception:
                    pass

    vault_nb_ids = {n["notebook_id"] for n in vault_notes if n["notebook_id"]}

    # 2. Get all notebooks from NotebookLM CLI
    list_out = run_cli_cmd('notebooklm list --json')
    if not list_out:
        print(json.dumps({"error": "Failed to list notebooks from CLI. Check auth."}))
        sys.exit(1)
        
    try:
        list_data = json.loads(list_out)
        if "error" in list_data and list_data["error"]:
            print(json.dumps({"error": list_data.get("message", "CLI Error")}))
            sys.exit(1)
        notebooks = list_data.get("notebooks", [])
    except Exception as e:
        print(json.dumps({"error": f"Failed to parse notebook list: {str(e)}\nRaw Output: {list_out[:100]}"}))
        sys.exit(1)

    # 3. Analyze differences
    new_notebooks = []
    skipped_notebooks = []

    for nb in notebooks:
        nb_id = nb.get("id")
        nb_title = nb.get("title", "")
        
        # If ID already exists in vault, skip
        if nb_id in vault_nb_ids:
            continue
            
        # Semantic check
        norm_nb_title = normalize_title(nb_title)
        best_match_ratio = 0
        best_match_title = ""
        
        for vn in vault_notes:
            ratio = difflib.SequenceMatcher(None, norm_nb_title, vn["normalized_title"]).ratio()
            if ratio > best_match_ratio:
                best_match_ratio = ratio
                best_match_title = vn["title"]
                
        if best_match_ratio > 0.85:
            skipped_notebooks.append({
                "id": nb_id,
                "title": nb_title,
                "reason": f"Semantic duplicate of '{best_match_title}' (similarity: {best_match_ratio:.2f})"
            })
        else:
            new_notebooks.append({
                "id": nb_id,
                "title": nb_title
            })

    report = {
        "new_notebooks": new_notebooks,
        "skipped_notebooks": skipped_notebooks
    }
    
    print(json.dumps(report, indent=2))

if __name__ == "__main__":
    main()
