import os
import re
import sys
import json
import subprocess
import shutil

vault_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
ATTACHMENTS_DIR = os.path.join(vault_dir, "99_System", "Attachments")

def notify(msg):
    """Outputs messages to stdout. Since Shell Commands is configured to show stdout as notifications, this displays in Obsidian."""
    print(msg)
    sys.stdout.flush()

def notify_error(msg):
    """Outputs errors to stderr."""
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.stderr.flush()

def run_cli_cmd(args):
    """Runs a notebooklm command and returns the JSON output or throws an error."""
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
    except subprocess.CalledProcessError as e:
        err_msg = e.stderr or e.stdout
        if "not authenticated" in err_msg.lower() or "login" in err_msg.lower():
            raise RuntimeError("NotebookLM is not authenticated. Please configure/re-import credentials in the Knowledge Pipeline settings tab in Obsidian, or run 'notebooklm login' in your system command prompt/PowerShell first!")
        if "ratelimiterror" in err_msg.lower():
            raise RuntimeError("NotebookLM API rate limit reached. Google restricts generating too many audio/video files in a short time. Please wait 10-15 minutes and try again.")
        raise RuntimeError(f"NotebookLM CLI failed: {err_msg.strip()}")

def update_frontmatter_id(file_path, notebook_id):
    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
        content = f.read()
    
    # Check if file starts with YAML frontmatter
    has_frontmatter = False
    if content.startswith("---"):
        # find the end of the frontmatter
        end_idx = content.find("---", 3)
        if end_idx != -1:
            has_frontmatter = True
            
    if has_frontmatter:
        # Check if notebook_id key exists in the frontmatter
        frontmatter = content[0:end_idx+3]
        if "notebook_id:" in frontmatter:
            # Replace it
            new_content = re.sub(
                r'notebook_id:\s*["\']?.*?["\']?(?=\r?\n)', 
                f'notebook_id: "{notebook_id}"', 
                content, 
                count=1
            )
        else:
            # Insert it right before the closing --- of the frontmatter
            closing_marker = content.rfind("---", 0, end_idx+3)
            if closing_marker != -1:
                new_content = content[:closing_marker] + f"notebook_id: \"{notebook_id}\"\n" + content[closing_marker:]
            else:
                new_content = content
    else:
        # Prepend a new frontmatter block
        new_content = f"---\nurl: \"\"\nnotebook_id: \"{notebook_id}\"\n---\n" + content
        
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(new_content)

def update_attachment_link(file_path, type_key, relative_attachment_path, link_label):
    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()
    
    if "### Generated Attachments" not in content:
        content += "\n\n### Generated Attachments\n- **Podcast Audio**: \n- **Cinematic Video**: \n"
        
    pattern = f"- \\*\\*{type_key}\\*\\*:\\s*(.*)"
    replacement = f"- **{type_key}**: ![[{relative_attachment_path}]]"
    
    new_content = re.sub(pattern, replacement, content)
    
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(new_content)

def latex_to_unicode(text):
    # Dictionary of common LaTeX math symbol replacements
    replacements = {
        r'\sum': '∑',
        r'\int': '∫',
        r'\alpha': 'α',
        r'\beta': 'β',
        r'\gamma': 'γ',
        r'\delta': 'δ',
        r'\epsilon': 'ε',
        r'\zeta': 'ζ',
        r'\eta': 'η',
        r'\theta': 'θ',
        r'\iota': 'ι',
        r'\kappa': 'κ',
        r'\lambda': 'λ',
        r'\mu': 'μ',
        r'\nu': 'ν',
        r'\xi': 'ξ',
        r'\pi': 'π',
        r'\rho': 'ρ',
        r'\sigma': 'σ',
        r'\tau': 'τ',
        r'\upsilon': 'υ',
        r'\phi': 'φ',
        r'\chi': 'χ',
        r'\psi': 'ψ',
        r'\omega': 'ω',
        r'\Gamma': 'Γ',
        r'\Delta': 'Δ',
        r'\Theta': 'Θ',
        r'\Lambda': 'Λ',
        r'\Xi': 'Ξ',
        r'\Pi': 'Π',
        r'\Sigma': 'Σ',
        r'\Upsilon': 'Υ',
        r'\Phi': 'Φ',
        r'\Psi': 'Ψ',
        r'\Omega': 'Ω',
        r'\infty': '∞',
        r'\partial': '∂',
        r'\nabla': '∇',
        r'\approx': '≈',
        r'\neq': '≠',
        r'\ne': '≠',
        r'\leq': '≤',
        r'\le': '≤',
        r'\geq': '≥',
        r'\ge': '≥',
        r'\times': '×',
        r'\div': '÷',
        r'\pm': '±',
        r'\cdot': '·',
        r'\hbar': 'ħ',
        r'\ell': 'ℓ',
        r'\rightarrow': '→',
        r'\leftarrow': '←',
        r'\leftrightarrow': '↔',
        r'\Rightarrow': '⇒',
        r'\Leftarrow': '⇐',
        r'\Leftrightarrow': '⇔',
        r'\forall': '∀',
        r'\exists': '∃',
        r'\in': '∈',
        r'\notin': '∉',
        r'\ni': '∋',
        r'$$': '',
        r'$': ''
    }

    superscripts = {
        '0': '⁰', '1': '¹', '2': '²', '3': '³', '4': '⁴',
        '5': '⁵', '6': '⁶', '7': '⁷', '8': '⁸', '9': '⁹',
        '+': '⁺', '-': '⁻', '=': '⁼', '(': '⁽', ')': '⁾',
        'a': 'ᵃ', 'b': 'ᵇ', 'c': 'ᶜ', 'd': 'ᵈ', 'e': 'ᵉ',
        'f': 'ᶠ', 'g': 'ᵍ', 'h': 'ʰ', 'i': 'ⁱ', 'j': 'ʲ',
        'k': 'ᵏ', 'l': 'ˡ', 'm': 'ᵐ', 'n': 'ⁿ', 'o': 'ᵒ',
        'p': 'ᵖ', 'r': 'ʳ', 's': 'ˢ', 't': 'ᵗ', 'u': 'ᵘ',
        'v': 'ᵛ', 'w': 'ʷ', 'x': 'ˣ', 'y': 'ʸ', 'z': 'ᶻ',
        'A': 'ᴬ', 'B': 'ᴮ', 'D': 'ᴰ', 'E': 'ᴱ', 'G': 'ᴳ',
        'H': 'ᴴ', 'I': 'ᴵ', 'J': 'ᴶ', 'K': 'ᴷ', 'L': 'ᴸ',
        'M': 'ᴹ', 'N': 'ᴺ', 'O': 'ᴼ', 'P': 'ᴾ', 'R': 'ᴿ',
        'T': 'ᵀ', 'U': 'ᵁ', 'W': 'ᵂ'
    }

    subscripts = {
        '0': '₀', '1': '₁', '2': '₂', '3': '₃', '4': '₄',
        '5': '₅', '6': '₆', '7': '₇', '8': '₈', '9': '₉',
        '+': '₊', '-': '₋', '=': '₌', '(': '₍', ')': '₎',
        'a': 'ₐ', 'e': 'ₑ', 'h': 'ₕ', 'i': 'ᵢ', 'j': 'ⱼ',
        'k': 'ₖ', 'l': 'ₗ', 'm': 'ₘ', 'n': 'ₙ', 'o': 'ₒ',
        'p': 'ₚ', 'r': 'ᵣ', 's': 'ₛ', 't': 'ₜ', 'u': 'ᵤ',
        'v': 'ᵥ', 'x': 'ₓ'
    }
    
    # Sort keys by length to avoid partial replacements (e.g. \neq before \ne)
    sorted_keys = sorted(replacements.keys(), key=len, reverse=True)
    
    cleaned = text
    for key in sorted_keys:
        cleaned = cleaned.replace(key, replacements[key])
        
    # Handle superscripts with curly braces ^{...}
    def replace_sup_braces(match):
        inner = match.group(1)
        return "".join(superscripts.get(c, c) for c in inner)
    cleaned = re.sub(r'\^\{([^}]+)\}', replace_sup_braces, cleaned)

    # Handle subscripts with curly braces _{...}
    def replace_sub_braces(match):
        inner = match.group(1)
        return "".join(subscripts.get(c, c) for c in inner)
    cleaned = re.sub(r'\_\{([^}]+)\}', replace_sub_braces, cleaned)

    # Handle single character superscripts ^x or ^T
    def replace_sup_single(match):
        c = match.group(1)
        return superscripts.get(c, f"^{c}")
    cleaned = re.sub(r'\^([a-zA-Z0-9\+\-\=])', replace_sup_single, cleaned)

    # Handle single character subscripts _x or _i
    def replace_sub_single(match):
        c = match.group(1)
        return subscripts.get(c, f"_{c}")
    cleaned = re.sub(r'\_([a-zA-Z0-9\+\-\=])', replace_sub_single, cleaned)
        
    return cleaned

def update_mindmap_diagram(file_path, json_path):
    try:
        import json
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            
        lines = ["mindmap"]
        
        def traverse(node, depth):
            name = node.get("name", "").strip()
            if not name:
                return
            cleaned_name = name.replace("[", "(").replace("]", ")").replace('"', "'")
            cleaned_name = latex_to_unicode(cleaned_name)
            indent = "  " * (depth + 1)
            if depth == 0:
                root_name = cleaned_name.replace("[", "").replace("]", "").replace("(", "").replace(")", "").replace('"', "").replace("'", "")
                lines.append(f"{indent}root(( {root_name} ))")
            else:
                lines.append(f"{indent}[\"{cleaned_name}\"]")
                
            for child in node.get("children", []):
                traverse(child, depth + 1)
                
        traverse(data, 0)
        mermaid_code = "\n".join(lines)
        
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
            
        section_title = "## 🧠 Mind Map Diagram"
        mermaid_block = f"{section_title}\n```mermaid\n{mermaid_code}\n```"
        
        if section_title in content:
            pattern = re.escape(section_title) + r".*?(?=\n##|$)"
            new_content = re.sub(pattern, mermaid_block, content, flags=re.DOTALL)
        else:
            new_content = content.rstrip() + "\n\n" + mermaid_block + "\n"
            
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(new_content)
            
        notify("Mermaid Mind Map diagram successfully added/updated in note.")
    except Exception as e:
        notify(f"Warning: Could not generate Mermaid Mind Map diagram: {e}")

def update_notebook_summary(file_path, summary_text):
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
            
        section_title = "## 📝 Summarization"
        summary_block = f"{section_title}\n{summary_text.strip()}\n"
        
        if section_title in content:
            # Replace current summarization block (up to next heading or end of file)
            pattern = re.escape(section_title) + r".*?(?=\n##|$)"
            new_content = re.sub(pattern, summary_block, content, flags=re.DOTALL)
        else:
            new_content = content.rstrip() + "\n\n" + summary_block + "\n"
            
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(new_content)
            
        notify("AI Summary successfully updated in note.")
    except Exception as e:
        notify(f"Warning: Could not update AI Summary in note: {e}")

def check_arxiv_url(url):
    """If url is an arXiv abstract, html, or pdf page, checks if the HTML full text version exists.
    If so, returns the HTML URL; otherwise, returns the PDF URL."""
    match = re.search(r'arxiv\.org/(abs|html|pdf)/(\d+\.\d+v?\d*)', url)
    if match:
        paper_id = match.group(2)
        html_url = f"https://arxiv.org/html/{paper_id}"
        pdf_url = f"https://arxiv.org/pdf/{paper_id}.pdf"
        try:
            import requests
            r = requests.head(html_url, allow_redirects=True, timeout=5)
            if r.status_code == 200:
                notify(f"ArXiv full HTML version found and selected: {html_url}")
                return html_url
        except Exception:
            pass
        notify(f"ArXiv full PDF version selected: {pdf_url}")
        return pdf_url
    return url

def main():
    if len(sys.argv) < 3:
        notify_error("Usage: python generate_artifact.py <file_path> <artifact_type>")
        sys.exit(1)

    file_path = sys.argv[1]
    artifact_type = sys.argv[2] # mind-map, audio, cinematic-video

    if not os.path.exists(file_path):
        notify_error(f"File not found: {file_path}")
        sys.exit(1)

    notify(f"Starting NotebookLM processing for {os.path.basename(file_path)}...")

    # 1. Parse File Frontmatter
    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
        content = f.read()

    # Simple regex to get frontmatter variables
    url_match = re.search(r'url:\s*["\']?(.*?)["\']?(?=\r?\n)', content)
    notebook_id_match = re.search(r'notebook_id:\s*["\']?(.*?)["\']?(?=\r?\n)', content)
    
    url = url_match.group(1).strip() if url_match else None
    notebook_id = notebook_id_match.group(1).strip() if notebook_id_match else None

    # Fallback if frontmatter URL is empty: search note body for a valid URL (excluding Google Keep links)
    if not url or url.strip() == "" or url.strip() == '""' or url.strip() == "''":
        body_urls = re.findall(r'https?://[^\s\)\]\u200b]+', content)
        for bu in body_urls:
            bu_clean = re.sub(r'^[\[\(\{\s]+|[\]\)\}\s\.\,]+$', '', bu)
            if "keep.google.com" not in bu_clean:
                url = bu_clean
                notify(f"Fallback: Found source URL in note body: {url}")
                break

    # Title is the first # heading or filename
    title_match = re.search(r'^#\s+(.*?)(?=\r?\n)', content, re.MULTILINE)
    note_title = title_match.group(1).strip() if title_match else os.path.splitext(os.path.basename(file_path))[0]

    # Resolve redirects (e.g. short links like share.google) to final URL if URL exists and is not Google Drive
    if url:
        is_drive = "docs.google.com" in url or "drive.google.com" in url
        if not is_drive:
            if "arxiv.org" in url:
                resolved_arxiv = check_arxiv_url(url)
                if resolved_arxiv != url:
                    try:
                        with open(file_path, "r", encoding="utf-8") as f:
                            note_content = f.read()
                        if "Full Version (HTML/PDF)" not in note_content:
                            fm_match = re.match(r"^---[\s\S]*?---\r?\n", note_content)
                            if fm_match:
                                end_fm = fm_match.end()
                                new_content = note_content[:end_fm] + f"\n> [!NOTE]\n> **Full Version (HTML/PDF)**: [Open full paper]({resolved_arxiv})\n\n" + note_content[end_fm:]
                            else:
                                new_content = f"> [!NOTE]\n> **Full Version (HTML/PDF)**: [Open full paper]({resolved_arxiv})\n\n" + note_content
                            with open(file_path, "w", encoding="utf-8") as f:
                                f.write(new_content)
                    except Exception as e:
                        notify(f"Warning: Could not add full version link to note: {e}")
                    url = resolved_arxiv
            else:
                try:
                    import requests
                    notify("Checking source URL for redirects...")
                    r = requests.get(url, allow_redirects=True, timeout=10, stream=True)
                    resolved_url = r.url
                    if resolved_url != url:
                        notify(f"Resolved URL: {resolved_url}")
                        url = resolved_url
                except Exception as e:
                    notify(f"Warning: Could not resolve URL redirects: {e}")

    # Clean note title for file names
    clean_title = re.sub(r'[\\/*?:"<>|]', "", note_title)[:60].strip()

    # 2. Check/Create Notebook
    try:
        if not notebook_id:
            notify(f"Creating new NotebookLM notebook: '{clean_title}'...")
            # We run create command
            create_out = run_cli_cmd(f'notebooklm create "{clean_title}" --json')
            try:
                notebook_data = json.loads(create_out)
                notebook_id = None
                if isinstance(notebook_data, list) and len(notebook_data) > 0:
                    item = notebook_data[0]
                else:
                    item = notebook_data
                
                if isinstance(item, dict):
                    notebook_id = item.get("id") or item.get("notebookId")
                    if not notebook_id and "notebook" in item and isinstance(item["notebook"], dict):
                        notebook_id = item["notebook"].get("id") or item["notebook"].get("notebookId")
                
                if not notebook_id:
                    raise ValueError("Notebook ID not found in JSON keys")
            except Exception:
                # Fallback regex parse if JSON is structured differently or has wrapper
                id_search = re.search(r'"(?:id|notebookId)":\s*"([^"]+)"', create_out)
                if id_search:
                    notebook_id = id_search.group(1)
            
            if not notebook_id:
                raise RuntimeError(f"Could not parse notebook ID from output: {create_out}")
            
            # Save ID back to file
            update_frontmatter_id(file_path, notebook_id)
            notify(f"Notebook created with ID: {notebook_id}")

            # Add source (URL, Google Drive document, or upload local file)
            try:
                drive_match = None
                if url:
                    drive_match = re.search(r'https?://(?:docs|drive)\.google\.com/(?:document|presentation|spreadsheets|file)/d/([a-zA-Z0-9_-]+)', url)

                if drive_match:
                    file_id = drive_match.group(1)
                    # Determine MIME type
                    mime_type = "google-doc"
                    if "/presentation/d/" in url:
                        mime_type = "google-slides"
                    elif "/spreadsheets/d/" in url:
                        mime_type = "google-sheets"
                    elif "/file/d/" in url:
                        if "pdf" in url.lower() or "pdf" in clean_title.lower():
                            mime_type = "pdf"
                    
                    notify(f"Google Drive link detected. Ingesting File ID: {file_id} with type: {mime_type}...")
                    run_cli_cmd(f'notebooklm source add-drive -n {notebook_id} --mime-type {mime_type} "{file_id}" "{clean_title}" --json')
                    notify("Google Drive document successfully added to notebook.")
                elif url:
                    notify(f"Adding source URL to notebook: {url}...")
                    run_cli_cmd(f'notebooklm source add -n {notebook_id} "{url}" --json')
                    notify("Source URL successfully added to notebook.")
                else:
                    notify("No source URL found. Preparing to upload active note content as source...")
                    # Read the note content and sanitize it
                    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                        note_raw = f.read()
                    
                    # Strip YAML frontmatter
                    note_clean = re.sub(r"^---[\s\S]*?---\r?\n", "", note_raw)
                    # Strip meta-bind-buttons
                    note_clean = re.sub(r"```meta-bind-button[\s\S]*?```\r?\n", "", note_clean)
                    # Strip section titles of artifacts
                    note_clean = note_clean.replace("## 🛠️ NotebookLM Artifacts", "")
                    note_clean = note_clean.replace("### Generated Attachments", "")
                    note_clean = note_clean.strip()
                    
                    # Write to a temporary file
                    import tempfile
                    temp_dir = tempfile.gettempdir()
                    temp_file_path = os.path.join(temp_dir, f"{clean_title}_source.txt")
                    
                    with open(temp_file_path, "w", encoding="utf-8") as temp_f:
                        temp_f.write(note_clean)
                    
                    try:
                        notify("Uploading active note content to NotebookLM...")
                        run_cli_cmd(f'notebooklm source add -n {notebook_id} --type file --title "{clean_title}" "{temp_file_path}" --json')
                        notify("Note content successfully uploaded to notebook.")
                    finally:
                        if os.path.exists(temp_file_path):
                            try:
                                os.remove(temp_file_path)
                            except Exception:
                                pass
            except Exception as e:
                # If adding source fails, clear the saved notebook_id so next run starts clean
                update_frontmatter_id(file_path, "")
                raise e
        else:
            notify(f"Using existing notebook ID: {notebook_id}")

        # Wait for all sources in the notebook to finish processing before generating artifacts
        try:
            notify("Verifying that all sources are fully processed and ready...")
            sources_json = run_cli_cmd(f'notebooklm source list -n {notebook_id} --json')
            sources = json.loads(sources_json)
            
            clean_source_title = None
            if isinstance(sources, list) and len(sources) > 0:
                for src in sources:
                    src_id = src.get("id") or src.get("sourceId")
                    if src_id:
                        src_title = src.get("title") or src_id
                        notify(f"Checking index status of source: '{src_title}'...")
                        run_cli_cmd(f'notebooklm source wait -n {notebook_id} "{src_id}" --timeout 180')
                        if src_title and "http" not in src_title.lower() and "www." not in src_title.lower() and len(src_title) > 5:
                            if not src_title.startswith("Source ") or len(src_title) > 25:
                                clean_source_title = src_title
            
            notify("All sources are ready.")
            
            # Fetch AI-generated summary from NotebookLM
            notebook_summary = ""
            try:
                notebook_summary = run_cli_cmd(f'notebooklm summary -n {notebook_id}').strip()
            except Exception:
                pass

            # Self-healing: Update frontmatter, title, and filename if they are currently generic/failed
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                note_content = f.read()

            updated = False
            
            # 1. Update summary if current is empty or generic
            if 'summarization: "No summary available."' in note_content or 'summarization: ""' in note_content or 'summarization: "None"' in note_content:
                if notebook_summary:
                    safe_summary = notebook_summary.replace("\n", " ").replace('"', '\\"')
                    note_content = re.sub(
                        r'summarization:\s*["\']?.*?["\']?(?=\r?\n)',
                        f'summarization: "{safe_summary}"',
                        note_content,
                        count=1
                    )
                    note_content = re.sub(
                        r'## 📝 Summarization\r?\n.*?(?=\r?\n##|$)',
                        f'## 📝 Summarization\n{notebook_summary}\n',
                        note_content,
                        flags=re.DOTALL
                    )
                    updated = True

            # 2. Update topic if generic
            if "topic: General Research" in note_content or "topic: \"\"" in note_content or "topic: ''" in note_content:
                inferred_topic = "General Research"
                text_for_topic = (clean_source_title or notebook_summary or "").lower()
                topic_keywords = {
                    "Artificial Intelligence": ["ai", "neural", "machine learning", "deep learning", "nlp", "llm", "transformers"],
                    "Physics": ["physics", "quantum", "gravity", "thermodynamics", "particles", "astronomy", "cosmic"],
                    "Biology": ["biology", "evolutionary", "cells", "protein", "dna", "rna", "gene", "medical", "brain", "neuroscience"],
                    "Mathematics": ["math", "calculus", "algebra", "geometry", "graph theory", "equations"],
                    "Software Development": ["software", "programming", "python", "javascript", "code", "git", "database"]
                }
                for top, keywords in topic_keywords.items():
                    if any(kw in text_for_topic for kw in keywords):
                        inferred_topic = top
                        break
                
                note_content = re.sub(
                    r'topic:\s*["\']?.*?["\']?(?=\r?\n)',
                    f'topic: {inferred_topic}',
                    note_content,
                    count=1
                )
                updated = True

            # 3. Update title and filename if current title/filename is generic
            is_generic_title = note_title.startswith("Source ") and ("http" in note_title or "www" in note_title or "2026-" in note_title)
            if is_generic_title and not clean_source_title:
                try:
                    notify("Querying NotebookLM for a clean article title...")
                    queried_title = run_cli_cmd(f'notebooklm query -n {notebook_id} "What is the exact title of the article or document in this notebook? Respond with ONLY the title. Do not include any extra text, quotes, or markdown."').strip()
                    queried_title = queried_title.replace('"', '').replace("'", "").strip()
                    if queried_title and "http" not in queried_title.lower() and len(queried_title) > 5 and len(queried_title) < 150:
                        clean_source_title = queried_title
                        notify(f"NotebookLM Query resolved clean title: '{clean_source_title}'")
                except Exception as e:
                    notify(f"Warning: Could not query title from NotebookLM: {e}")

            if is_generic_title and clean_source_title:
                note_content = re.sub(
                    r'^#\s+.*?(?=\r?\n)',
                    f'# {clean_source_title}',
                    note_content,
                    count=1,
                    flags=re.MULTILINE
                )
                updated = True
                
                with open(file_path, "w", encoding="utf-8") as f:
                    f.write(note_content)
                updated = False
                
                new_clean_title = re.sub(r'[\\/*?:"<>|]', "", clean_source_title)[:60].strip()
                new_filename = f"{new_clean_title}.md"
                new_file_path = os.path.join(os.path.dirname(file_path), new_filename)
                
                if file_path != new_file_path:
                    notify(f"Self-healing: Renaming generic note file to '{new_filename}'...")
                    if os.path.exists(new_file_path):
                        os.remove(new_file_path)
                    os.rename(file_path, new_file_path)
                    file_path = new_file_path
                    clean_title = new_clean_title
                    note_title = clean_source_title

            if updated:
                with open(file_path, "w", encoding="utf-8") as f:
                    f.write(note_content)

        except Exception as e:
            notify(f"Warning: Could not verify sources readiness or self-heal metadata: {e}")

        # 3. Generate Artifact
        notify(f"Generating {artifact_type} in NotebookLM (this might take a minute)...")
        if artifact_type == "summary":
            notify("Fetching AI-generated notebook summary...")
            summary_output = run_cli_cmd(f'notebooklm summary -n {notebook_id}')
            update_notebook_summary(file_path, summary_output)
            notify("Summary updated successfully.")
            
        elif artifact_type == "mind-map":
            run_cli_cmd(f'notebooklm generate mind-map -n {notebook_id} --json')
            notify("Mind Map generation complete.")
            
            # Download mind-map as a temporary file
            dest_filename = f"{clean_title} Mind Map.json"
            dest_path = os.path.join(ATTACHMENTS_DIR, dest_filename)
            notify("Downloading Mind Map JSON...")
            run_cli_cmd(f'notebooklm download mind-map -n {notebook_id} --latest "{dest_path}"')
            
            # Parse and render into note
            update_mindmap_diagram(file_path, dest_path)
            
            # Clean up the JSON file since we only need the Mermaid diagram
            try:
                if os.path.exists(dest_path):
                    os.remove(dest_path)
                    notify("Cleaned up temporary JSON file.")
            except Exception as e:
                notify(f"Warning: Could not remove temporary JSON: {e}")
                
            notify("Success! Mind Map generated and added as a Mermaid diagram.")

        elif artifact_type == "audio":
            notify("Starting audio overview generation (deep-dive format). This takes 1-3 minutes...")
            run_cli_cmd(f'notebooklm generate audio -n {notebook_id} --format deep-dive --wait --retry 5 --json')
            notify("Audio generation complete.")
            
            dest_filename = f"{clean_title} Podcast.mp3"
            dest_path = os.path.join(ATTACHMENTS_DIR, dest_filename)
            notify("Downloading Podcast Audio...")
            import tempfile
            temp_audio_path = os.path.join(tempfile.gettempdir(), f"temp_{dest_filename}")
            if os.path.exists(temp_audio_path):
                try:
                    os.remove(temp_audio_path)
                except Exception:
                    pass
            run_cli_cmd(f'notebooklm download audio -n {notebook_id} --latest "{temp_audio_path}"')
            shutil.move(temp_audio_path, dest_path)
            
            update_attachment_link(file_path, "Podcast Audio", f"99_System/Attachments/{dest_filename}", "Podcast (MP3)")
            notify(f"Success! Podcast downloaded and linked to note: {dest_filename}")

        elif artifact_type == "cinematic-video":
            notify("Starting video overview generation. This takes 1-3 minutes...")
            try:
                run_cli_cmd(f'notebooklm generate cinematic-video -n {notebook_id} --wait --retry 5 --json')
                notify("Cinematic video generation complete.")
                
                dest_filename = f"{clean_title} Video.mp4"
                dest_path = os.path.join(ATTACHMENTS_DIR, dest_filename)
                notify("Downloading Cinematic Video File...")
                import tempfile
                temp_video_path = os.path.join(tempfile.gettempdir(), f"temp_{dest_filename}")
                if os.path.exists(temp_video_path):
                    try:
                        os.remove(temp_video_path)
                    except Exception:
                        pass
                run_cli_cmd(f'notebooklm download cinematic-video -n {notebook_id} --latest "{temp_video_path}"')
                shutil.move(temp_video_path, dest_path)
            except Exception as e:
                err_str = str(e).lower()
                if "not authenticated" in err_str or "login" in err_str:
                    raise e
                else:
                    notify(f"Warning: Cinematic video generation failed: {e}. Falling back to standard video overview...")
                    run_cli_cmd(f'notebooklm generate video -n {notebook_id} --wait --retry 5 --json')
                    notify("Standard video generation complete.")
                    
                    dest_filename = f"{clean_title} Video.mp4"
                    dest_path = os.path.join(ATTACHMENTS_DIR, dest_filename)
                    notify("Downloading Video File...")
                    import tempfile
                    temp_video_path = os.path.join(tempfile.gettempdir(), f"temp_{dest_filename}")
                    if os.path.exists(temp_video_path):
                        try:
                            os.remove(temp_video_path)
                        except Exception:
                            pass
                    run_cli_cmd(f'notebooklm download video -n {notebook_id} --latest "{temp_video_path}"')
                    shutil.move(temp_video_path, dest_path)
            
            update_attachment_link(file_path, "Cinematic Video", f"99_System/Attachments/{dest_filename}", "Video (MP4)")
            notify(f"Success! Video downloaded and linked to note: {dest_filename}")

        else:
            notify_error(f"Unknown artifact type: {artifact_type}")

    except Exception as e:
        notify_error(str(e))
        sys.exit(1)

if __name__ == "__main__":
    main()
