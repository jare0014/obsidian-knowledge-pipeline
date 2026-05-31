# Knowledge Pipeline Obsidian Plugin

This plugin processes imported web links in your vault, scrapes their content, generates high-quality AI summaries, and structures them as research documents. It also renders interactive buttons to trigger external NotebookLM generation scripts.

---

## 🛠️ Features

1. **Automatic URL Scraping**: Scans your target imports folder for any text files containing web links, extracts the content, and scrapes the title/body text.
2. **AI-Powered Summarization**:
   * **Gemini**: Secure cloud summaries via Google Gemini models (credentials are stored securely in the system keychain).
   * **Ollama**: Free, local, private offline summaries via Ollama servers (supports models like Qwen 2.5, Gemma 3, etc.).
3. **Structured Research Vaulting**: Adds standardized frontmatter (YAML) to the note with topic classification and summarization, renaming the note properly.
4. **NotebookLM Action Buttons**: Sets up `meta-bind-button` elements directly in the notes to trigger shell script builds for Mind Maps, Podcasts, and Videos.

---

## 🔒 Configuration & AI Backend Setup

Go to **Settings** > **Knowledge Pipeline** in Obsidian:

### 1. Target Folder
* **Imports Target Folder**: Set the folder relative to your vault root containing imported links to process (default: `00_Imports`).

### 2. Provider Options

#### Option A: Google Gemini (Recommended)
1. Set **LLM Provider** to `Gemini (Google Cloud)`.
2. Enter your **Gemini API Key** in the secure password-masked input. The API key is stored in your OS keychain via Obsidian's secure storage (`knowledge-pipeline-gemini-api-key`).
3. Select your model (e.g. `Gemini 2.5 Flash`, `Gemini 2.5 Pro`).

#### Option B: Ollama (Local & Private)
1. Make sure you have Ollama running locally (`http://localhost:11434`).
2. Set **LLM Provider** to `Ollama (Local)`.
3. Provide your **Ollama Endpoint** (default: `http://localhost:11434`).
4. Select one of the default models (e.g. `Qwen 2.5 7B`, `Gemma 3 4B`) or choose `Custom...` and specify your exact model tag (e.g., `llama3:8b`).

---

## 🚀 Usage Flow

1. Create a markdown note in your target folder (e.g. `00_Imports/New research.md`) containing just a URL of a web article or paper (e.g. `https://example.com/some-quantum-article`).
2. Open the Command Palette (`Ctrl + P` / `Cmd + P`).
3. Run: `Knowledge Pipeline: Import and Summarize Share Links`.
4. The plugin will scrape the link, run it through the selected LLM, structure the document, and add NotebookLM generator actions.

---

## 🧠 NotebookLM Shell Action Buttons

Each successfully structured note includes interactive buttons:
* **Generate Mind Map** (runs command `obsidian-shellcommands:shell-command-nb-mindmap`)
* **Generate Podcast (Audio)** (runs command `obsidian-shellcommands:shell-command-nb-podcast`)
* **Generate Cinematic Video** (runs command `obsidian-shellcommands:shell-command-nb-video`)

These buttons trigger Obsidian shell commands linked to your external automation scripts, which process the document's URL/summary.
