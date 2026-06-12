const obsidian = require('obsidian');

const DEFAULT_SETTINGS = {
    importsFolder: '00_Imports',
    geminiApiKeyId: 'knowledge-pipeline-gemini-api-key',
    llmProvider: 'gemini',
    llmModel: 'gemini-2.5-flash',
    customModel: '',
    ollamaUrl: 'http://localhost:11434'
};

class KnowledgePipelinePlugin extends obsidian.Plugin {
    async onload() {
        await this.loadSettings();

        // Add settings tab
        this.addSettingTab(new KnowledgePipelineSettingTab(this.app, this));

        // Add command to process imports
        this.addCommand({
            id: 'process-imports',
            name: 'Import and Summarize Share Links',
            callback: () => this.processImports()
        });

        // Add commands for NotebookLM generation
        this.addCommand({
            id: 'generate-mind-map',
            name: 'NotebookLM: Generate Mind Map',
            callback: () => this.runArtifactGenerator('mind-map')
        });
        this.addCommand({
            id: 'generate-podcast',
            name: 'NotebookLM: Generate Podcast',
            callback: () => this.runArtifactGenerator('audio')
        });
        this.addCommand({
            id: 'generate-video',
            name: 'NotebookLM: Generate Cinematic Video',
            callback: () => this.runArtifactGenerator('cinematic-video')
        });

        this.addCommand({
            id: 'import-notebooks',
            name: 'NotebookLM: Sync New Notebooks',
            callback: () => this.runNotebookSync()
        });

        // Setup status bar item for NotebookLM session status
        this.statusBarItemEl = this.addStatusBarItem();
        this.updateStatusBar();

        // Setup periodic check every 5 minutes
        this.registerInterval(
            window.setInterval(() => this.updateStatusBar(), 5 * 60 * 1000)
        );

        // Run legacy notes buttons migration
        this.app.workspace.onLayoutReady(() => {
            this.migrateExistingNotes();
        });
    }

    async loadSettings() {
        this.settings = Object.assign({}, DEFAULT_SETTINGS, await this.loadData());
    }

    async saveSettings() {
        await this.saveData(this.settings);
    }

    async processImports() {
        try {
            new obsidian.Notice("Scanning imports folder...");
            
            const importsFolder = this.settings.importsFolder || '00_Imports';
            const files = this.app.vault.getMarkdownFiles();
            
            let convertedCount = 0;
            let errors = 0;
            let matchedFilesCount = 0;
            
            if (!this.app.secretStorage) {
                new obsidian.Notice("Error: secretStorage is not available in this Obsidian version!");
                return;
            }
            
            new obsidian.Notice(`Found ${files.length} markdown files in vault.`);

            // Loop through all markdown files in the target folder
            for (const file of files) {
                const normalizedPath = file.path.replace(/\\/g, '/');
                const targetPrefix = importsFolder.replace(/\\/g, '/').replace(/\/+$/, '') + '/';
                
                if (normalizedPath.startsWith(targetPrefix)) {
                    matchedFilesCount++;
                    try {
                        const content = await this.app.vault.read(file);
                        
                        // Skip files that are already structured
                        if (content.trim().startsWith("---") && content.includes("url:")) {
                            continue;
                        }
                        
                        // Find URL
                        const urls = content.match(/https?:\/\/[^\s\)\]\u200b]+/g);
                        let targetUrl = null;
                        if (urls) {
                            for (let url of urls) {
                                if (!url.includes('keep.google.com')) {
                                    targetUrl = url;
                                    break;
                                }
                            }
                        }
                        
                        if (!targetUrl) {
                            new obsidian.Notice(`File ${file.name} has no valid URLs.`);
                            continue; // Not a link note
                        }
                        
                        // Clean brackets/parentheses from url end/start
                        targetUrl = targetUrl.replace(/^[\[\(\{\s]+|[\]\)\}\s]+$/g, '');
                        
                        new obsidian.Notice(`Scraping: ${file.name}`);
                        
                        // 1. Scrape URL
                        const pageData = await this.scrapeUrl(targetUrl);
                        
                        let title = file.basename;
                        let description = "";
                        let body = "";
                        
                        if (pageData) {
                            description = pageData.description || "";
                            body = pageData.body || "";
                            if (pageData.title && pageData.title.length > 10) {
                                title = pageData.title;
                            }
                        } else {
                            new obsidian.Notice(`Warning: Scraping failed for ${targetUrl}. Using heuristics.`);
                        }
                        
                        // Clean title for markdown heading/YAML
                        title = title.replace(/\n/g, " ").replace(/"/g, '\\"').trim();
                        
                        let summary = "";
                        if (this.settings.llmProvider === 'ollama') {
                            const ollamaUrl = this.settings.ollamaUrl || 'http://localhost:11434';
                            const modelName = this.settings.llmModel || 'qwen2.5:7b';
                            new obsidian.Notice(`Summarizing with Ollama: ${file.name}`);
                            summary = await this.getOllamaSummary(ollamaUrl, modelName, title, description, body);
                        } else {
                            const secretId = this.settings.geminiApiKeyId || 'knowledge-pipeline-gemini-api-key';
                            let geminiApiKey = await this.app.secretStorage.getSecret(secretId) || '';
                            if (!geminiApiKey) {
                                geminiApiKey = await this.app.secretStorage.getSecret('timeblocker-gemini-api-key') || '';
                            }
                            
                            if (!geminiApiKey) {
                                new obsidian.Notice("Error: Gemini API key is missing! Please configure it in settings.");
                                continue;
                            }
                            
                            const modelName = this.settings.llmModel || 'gemini-2.5-flash';
                            new obsidian.Notice(`Summarizing with Gemini: ${file.name}`);
                            summary = await this.getGeminiSummary(geminiApiKey, modelName, title, description, body);
                        }
                        
                        // Guess general topic based on title keywords
                        let topic = "General Research";
                        const keywords = ["quantum", "ai", "physics", "biology", "brain", "neuroscience", "math", "software", "google", "git", "sql"];
                        for (const kw of keywords) {
                            if (title.toLowerCase().includes(kw)) {
                                topic = kw.charAt(0).toUpperCase() + kw.slice(1);
                                break;
                            }
                        }
                        
                        const structuredContent = `---
url: ${targetUrl}
topic: ${topic}
summarization: "${summary.replace(/"/g, '\\"')}"
notebook_id: ""
---
# ${title}

**Original Source**: [${targetUrl}](${targetUrl})

## 📝 Summarization
${summary}

## 🛠️ NotebookLM Artifacts
\`\`\`meta-bind-button
label: 🧠 Generate Mind Map
icon: "git-branch"
style: primary
hidden: false
actions:
  - type: command
    command: knowledge-pipeline:generate-mind-map
\`\`\`
\`\`\`meta-bind-button
label: 🎙️ Generate Podcast (Audio)
icon: "headphones"
style: primary
hidden: false
actions:
  - type: command
    command: knowledge-pipeline:generate-podcast
\`\`\`
\`\`\`meta-bind-button
label: 🎬 Generate Cinematic Video
icon: "video"
style: primary
hidden: false
actions:
  - type: command
    command: knowledge-pipeline:generate-video
\`\`\`

### Generated Attachments
- **Podcast Audio**: 
- **Cinematic Video**: 
`;
                        await this.app.vault.modify(file, structuredContent);
                        convertedCount++;
                        new obsidian.Notice(`Successfully structured: ${file.name}`);
                        
                        if (convertedCount >= 10) {
                            new obsidian.Notice("Processed limit of 10 unstructured files.");
                            break;
                        }
                    } catch (e) {
                        console.error(`Error processing file ${file.path}:`, e);
                        new obsidian.Notice(`Error processing ${file.name}: ${e.message}`);
                        errors++;
                    }
                }
            }
            
            new obsidian.Notice(`Matched ${matchedFilesCount} files in '${importsFolder}'. Converted: ${convertedCount}, Errors: ${errors}`);
        } catch (globalError) {
            console.error("Global pipeline error:", globalError);
            new obsidian.Notice(`Global Pipeline Error: ${globalError.message}`);
        }
    }

    async scrapeUrl(url) {
        try {
            const response = await obsidian.requestUrl({
                url: url,
                headers: {
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                }
            });
            
            if (response.status !== 200) {
                return null;
            }
            
            let htmlText = "";
            if (response.arrayBuffer) {
                htmlText = new TextDecoder("utf-8").decode(response.arrayBuffer);
            } else {
                htmlText = response.text;
            }

            const parser = new DOMParser();
            const doc = parser.parseFromString(htmlText, "text/html");
            
            const title = doc.querySelector("title")?.textContent?.trim() || "";
            
            let description = "";
            const descTag = doc.querySelector('meta[name="description"]') || 
                            doc.querySelector('meta[property="og:description"]');
            if (descTag) {
                description = descTag.getAttribute("content")?.trim() || "";
            }
            
            const paragraphs = Array.from(doc.querySelectorAll("p"))
                .map(p => p.textContent.trim())
                .filter(Boolean);
            const body = paragraphs.join(" ").substring(0, 3000);
            
            return { title, description, body };
        } catch (e) {
            console.error(`Error scraping URL ${url}:`, e);
            return null;
        }
    }

    async getGeminiSummary(apiKey, modelName, title, description, body) {
        let model = modelName;
        
        const url = `https://generativelanguage.googleapis.com/v1beta/models/${model}:generateContent?key=${apiKey}`;
        const prompt = `You are a helpful reading assistant. Summarize the following web page content in 2-3 sentences. Do not use double quotes in your output.
Title: ${title}
Description: ${description}
Content: ${body}`;

        try {
            const response = await obsidian.requestUrl({
                url: url,
                method: "POST",
                headers: {
                    "Content-Type": "application/json"
                },
                body: JSON.stringify({
                    contents: [{
                        parts: [{ text: prompt }]
                    }]
                })
            });
            
            if (response.status !== 200) {
                if (model !== "gemini-1.5-flash") {
                    return this.getGeminiSummary(apiKey, "gemini-1.5-flash", title, description, body);
                }
                throw new Error(`Gemini API returned status ${response.status}: ${response.text}`);
            }
            
            const data = JSON.parse(response.text);
            const text = data.candidates?.[0]?.content?.parts?.[0]?.text?.trim() || "";
            if (!text) {
                throw new Error("Empty response from Gemini API");
            }
            return text;
        } catch (e) {
            console.error("Gemini summary error:", e);
            if (description) {
                return `${description} (Heuristic summary extracted from page description)`;
            } else if (body) {
                return `${body.substring(0, 200)}... (Heuristic preview)`;
            }
            return "No summary available. Click NotebookLM buttons to process further.";
        }
    }

    async getOllamaSummary(endpoint, modelName, title, description, body) {
        const url = `${endpoint.replace(/\/+$/, '')}/api/generate`;
        const prompt = `You are a helpful reading assistant. Summarize the following web page content in 2-3 sentences. Do not use double quotes in your output.
Title: ${title}
Description: ${description}
Content: ${body}`;

        try {
            const response = await obsidian.requestUrl({
                url: url,
                method: "POST",
                headers: {
                    "Content-Type": "application/json"
                },
                body: JSON.stringify({
                    model: modelName,
                    prompt: prompt,
                    stream: false
                })
            });
            
            if (response.status !== 200) {
                throw new Error(`Ollama API returned status ${response.status}: ${response.text}`);
            }
            
            const data = JSON.parse(response.text);
            const text = data.response?.trim() || "";
            if (!text) {
                throw new Error("Empty response from Ollama API");
            }
            return text;
        } catch (e) {
            console.error("Ollama summary error:", e);
            if (description) {
                return `${description} (Heuristic summary extracted from page description)`;
            } else if (body) {
                return `${body.substring(0, 200)}... (Heuristic preview)`;
            }
            return "No summary available. Click NotebookLM buttons to process further.";
        }
    }

    async runArtifactGenerator(type) {
        const activeFile = this.app.workspace.getActiveFile();
        if (!activeFile) {
            new obsidian.Notice("Error: No active file found! Please open a note first.");
            return;
        }

        const path = require('path');
        const vaultPath = this.app.vault.adapter.getBasePath();
        const absoluteFilePath = path.join(vaultPath, activeFile.path);
        await this.runArtifactGeneratorForFile(absoluteFilePath, type);
    }

    async runArtifactGeneratorForFile(absoluteFilePath, type) {
        try {
            const secretId = 'knowledge-pipeline-notebooklm-session';
            const sessionJson = await this.app.secretStorage.getSecret(secretId) || '';
            
            if (!sessionJson) {
                new obsidian.Notice("Error: NotebookLM session credentials not found in keychain! Please check settings to login and import credentials.");
                return;
            }

            const child_process = require('child_process');
            const path = require('path');
            const fs = require('fs');

            const vaultPath = this.app.vault.adapter.getBasePath();
            const scriptPath = path.join(vaultPath, '.obsidian', 'plugins', 'knowledge-pipeline', 'generate_artifact.py');

            if (!fs.existsSync(scriptPath)) {
                new obsidian.Notice(`Error: Generator script not found at ${scriptPath}`);
                return;
            }

            const filename = path.basename(absoluteFilePath);
            new obsidian.Notice(`[NotebookLM] Starting ${type} generation for ${filename}...`);

            const env = Object.assign({}, process.env, {
                NOTEBOOKLM_AUTH_JSON: sessionJson
            });

            const child = child_process.spawn('python', ['-u', scriptPath, absoluteFilePath, type], {
                cwd: path.dirname(scriptPath),
                env: env
            });

            child.stdout.on('data', (data) => {
                const text = data.toString().trim();
                if (text) {
                    console.log(`[NotebookLM stdout] ${text}`);
                    text.split('\n').forEach(line => {
                        const trimmed = line.trim();
                        if (trimmed) {
                            new obsidian.Notice(trimmed, 5000);
                        }
                    });
                }
            });

            child.stderr.on('data', (data) => {
                const text = data.toString().trim();
                if (text) {
                    console.error(`[NotebookLM stderr] ${text}`);
                    text.split('\n').forEach(line => {
                        const trimmed = line.trim();
                        if (trimmed) {
                            new obsidian.Notice(`Error: ${trimmed}`, 8000);
                        }
                    });
                }
            });

            child.on('close', (code) => {
                if (code === 0) {
                    new obsidian.Notice(`Success: NotebookLM ${type} processing complete for ${filename}!`);
                } else {
                    new obsidian.Notice(`Error: NotebookLM ${type} failed for ${filename} with exit code ${code}.`);
                }
            });

        } catch (err) {
            console.error("Artifact generator error:", err);
            new obsidian.Notice(`Error spawning artifact generator: ${err.message}`);
        }
    }

    async migrateExistingNotes() {
        try {
            const importsFolder = this.settings.importsFolder || '00_Imports';
            const files = this.app.vault.getMarkdownFiles();
            const targetPrefix = importsFolder.replace(/\\/g, '/').replace(/\/+$/, '') + '/';
            
            let migratedCount = 0;
            
            for (const file of files) {
                const normalizedPath = file.path.replace(/\\/g, '/');
                if (normalizedPath.startsWith(targetPrefix)) {
                    const content = await this.app.vault.read(file);
                    let changed = false;
                    let newContent = content;
                    
                    if (newContent.includes("command: obsidian-shellcommands:shell-command-nb-mindmap")) {
                        newContent = newContent.replace(/command:\s*obsidian-shellcommands:shell-command-nb-mindmap/g, "command: knowledge-pipeline:generate-mind-map");
                        changed = true;
                    }
                    if (newContent.includes("command: obsidian-shellcommands:shell-command-nb-podcast")) {
                        newContent = newContent.replace(/command:\s*obsidian-shellcommands:shell-command-nb-podcast/g, "command: knowledge-pipeline:generate-podcast");
                        changed = true;
                    }
                    if (newContent.includes("command: obsidian-shellcommands:shell-command-nb-video")) {
                        newContent = newContent.replace(/command:\s*obsidian-shellcommands:shell-command-nb-video/g, "command: knowledge-pipeline:generate-video");
                        changed = true;
                    }
                    
                    if (changed) {
                        await this.app.vault.modify(file, newContent);
                        migratedCount++;
                    }
                }
            }
            if (migratedCount > 0) {
                console.log(`[Knowledge Pipeline] Securely migrated ${migratedCount} link note buttons to native commands.`);
            }
        } catch (e) {
            console.error("Failed to migrate existing notes:", e);
        }
    }

    async runNotebookSync() {
        try {
            const secretId = 'knowledge-pipeline-notebooklm-session';
            const sessionJson = await this.app.secretStorage.getSecret(secretId) || '';
            
            if (!sessionJson) {
                new obsidian.Notice("Error: NotebookLM session credentials not found in keychain! Please check settings to login.");
                return;
            }

            const loadingNotice = new obsidian.Notice("Scanning for new NotebookLM notebooks...", 0);
            
            const child_process = require('child_process');
            const path = require('path');
            const fs = require('fs');

            const vaultPath = this.app.vault.adapter.getBasePath();
            const scriptPath = path.join(vaultPath, '.obsidian', 'plugins', 'knowledge-pipeline', 'import_notebooks.py');

            if (!fs.existsSync(scriptPath)) {
                loadingNotice.hide();
                new obsidian.Notice(`Error: Import script not found at ${scriptPath}`);
                return;
            }

            const env = Object.assign({}, process.env, {
                NOTEBOOKLM_AUTH_JSON: sessionJson
            });

            child_process.execFile('python', ['-u', scriptPath, vaultPath], { cwd: path.dirname(scriptPath), env: env, maxBuffer: 1024 * 1024 * 10 }, (err, stdout, stderr) => {
                loadingNotice.hide();
                if (err) {
                    console.error("Sync scan failed:", stderr || stdout);
                    new obsidian.Notice(`Sync Scan Failed: ${stderr || stdout}`);
                    return;
                }

                try {
                    const report = JSON.parse(stdout);
                    if (report.error) {
                        new obsidian.Notice(`Sync Scan Failed: ${report.error}`);
                        return;
                    }
                    
                    const newNbs = report.new_notebooks || [];
                    const duplicateNbs = report.skipped_notebooks || [];
                    
                    if (newNbs.length === 0 && duplicateNbs.length === 0) {
                        new obsidian.Notice("All your NotebookLM notebooks are already imported! Sync complete.");
                    } else {
                        new NotebookLMImportModal(this.app, this, newNbs, duplicateNbs).open();
                    }
                } catch (parseErr) {
                    console.error("Failed to parse sync report:", stdout);
                    new obsidian.Notice("Failed to parse sync scan report.");
                }
            });

        } catch (err) {
            console.error("Sync error:", err);
            new obsidian.Notice(`Sync Failed: ${err.message}`);
        }
    }
    
    async createLandingPage(nb) {
        try {
            const importsFolder = this.settings.importsFolder || '00_Imports';
            let title = nb.title.replace(/[\/\\:*?"<>|]/g, '-').trim();
            if (!title) title = nb.id;
            
            const targetPrefix = importsFolder.replace(/\\/g, '/').replace(/\/+$/, '') + '/';
            let targetPath = `${targetPrefix}${title}.md`;
            
            let counter = 1;
            while (await this.app.vault.adapter.exists(targetPath)) {
                targetPath = `${targetPrefix}${title} (${counter}).md`;
                counter++;
            }
            
            const targetUrl = `https://notebooklm.google.com/notebook/${nb.id}`;
            const summary = "Imported from NotebookLM sync. Click buttons to generate artifacts.";
            
            const structuredContent = `---
url: ${targetUrl}
topic: NotebookLM Import
summarization: "${summary}"
notebook_id: "${nb.id}"
---
# ${title}

**Original Source**: [NotebookLM Project](${targetUrl})

## 📝 Summarization
${summary}

## 🛠️ NotebookLM Artifacts
\`\`\`meta-bind-button
label: 🧠 Generate Mind Map
icon: "git-branch"
style: primary
hidden: false
actions:
  - type: command
    command: knowledge-pipeline:generate-mind-map
\`\`\`
\`\`\`meta-bind-button
label: 🎙️ Generate Podcast (Audio)
icon: "headphones"
style: primary
hidden: false
actions:
  - type: command
    command: knowledge-pipeline:generate-podcast
\`\`\`
\`\`\`meta-bind-button
label: 🎬 Generate Cinematic Video
icon: "video"
style: primary
hidden: false
actions:
  - type: command
    command: knowledge-pipeline:generate-video
\`\`\`

### Generated Attachments
- **Podcast Audio**: 
- **Cinematic Video**: 
`;
            await this.app.vault.create(targetPath, structuredContent);
            return true;
        } catch (err) {
            console.error("Failed to create landing page:", err);
            new obsidian.Notice(`Error creating note for ${nb.title}: ${err.message}`);
            return false;
        }
    }

    async launchLogin() {
        try {
            const os = require('os');
            const path = require('path');
            const fs = require('fs');
            const child_process = require('child_process');

            new obsidian.Notice("Launching NotebookLM login. Please log in using the browser window that opens...");

            const homeDir = os.homedir();
            const storagePath = path.join(homeDir, '.notebooklm', 'profiles', 'default', 'storage_state.json');

            // Delete existing storage_state.json first if it exists, so we are sure we get a fresh login
            if (fs.existsSync(storagePath)) {
                try {
                    fs.unlinkSync(storagePath);
                } catch (e) {
                    // Backup if unable to delete directly
                    const bakPath = storagePath + '.bak';
                    if (fs.existsSync(bakPath)) {
                        fs.unlinkSync(bakPath);
                    }
                    fs.renameSync(storagePath, bakPath);
                }
            }

            // Command to run in a separate window and wait
            const cmd = 'powershell.exe';
            const args = ['-NoProfile', '-Command', "Start-Process notebooklm -ArgumentList 'login' -Wait"];

            const child = child_process.spawn(cmd, args);

            child.on('close', async (code) => {
                // Once the window closes, check if the file was created
                if (!fs.existsSync(storagePath)) {
                    new obsidian.Notice("Authentication cancelled or failed (storage_state.json not found).");
                    await this.updateStatusBar();
                    return;
                }

                try {
                    const sessionJson = fs.readFileSync(storagePath, 'utf8');
                    // Simple validation of the JSON
                    try {
                        const parsed = JSON.parse(sessionJson);
                        if (!parsed.cookies || parsed.cookies.length === 0) {
                            new obsidian.Notice("Warning: Imported session JSON appears to contain no cookies.");
                        }
                    } catch (e) {
                        new obsidian.Notice("Error: Invalid JSON structure in storage_state.json.");
                        await this.updateStatusBar();
                        return;
                    }

                    // Verify that the credentials are valid by running a test command
                    const testEnv = Object.assign({}, process.env, {
                        NOTEBOOKLM_AUTH_JSON: sessionJson.trim()
                    });
                    child_process.exec('notebooklm list --json', { env: testEnv, timeout: 10000 }, async (testErr, testStdout, testStderr) => {
                        const testOutput = (testStdout || '') + (testStderr || '');
                        if (testErr || testOutput.toLowerCase().includes('not logged in') || testOutput.toLowerCase().includes('expired')) {
                            new obsidian.Notice(`Authentication check failed: ${testOutput.trim() || 'Invalid credentials'}`);
                            await this.updateStatusBar();
                            return;
                        }

                        // Save to SecretStorage
                        const secretId = 'knowledge-pipeline-notebooklm-session';
                        await this.app.secretStorage.setSecret(secretId, sessionJson.trim());

                        // Rename storage_state.json to storage_state.json.bak
                        const bakPath = storagePath + '.bak';
                        if (fs.existsSync(bakPath)) {
                            fs.unlinkSync(bakPath); // Delete old backup if it exists
                        }
                        fs.renameSync(storagePath, bakPath);

                        new obsidian.Notice("Success: NotebookLM credentials successfully saved to keychain and local file secured!");
                        await this.updateStatusBar();
                    });
                } catch (err) {
                    console.error("Import error:", err);
                    new obsidian.Notice(`Import Failed: ${err.message}`);
                    await this.updateStatusBar();
                }
            });

        } catch (err) {
            console.error("Login spawn error:", err);
            new obsidian.Notice(`Failed to start login process: ${err.message}`);
        }
    }

    async updateStatusBar() {
        if (!this.statusBarItemEl) {
            this.statusBarItemEl = this.addStatusBarItem();
        }
        
        // Bind click handler if not already set
        this.statusBarItemEl.onclick = () => {
            this.launchLogin();
        };

        try {
            const secretId = 'knowledge-pipeline-notebooklm-session';
            const sessionJson = await this.app.secretStorage.getSecret(secretId) || '';

            if (!sessionJson) {
                this.statusBarItemEl.setText("⚠️ Re-auth NotebookLM");
                this.statusBarItemEl.title = "No credentials found in keychain. Click to launch login.";
                this.statusBarItemEl.style.color = "var(--text-error)";
                this.statusBarItemEl.style.cursor = "pointer";
                return;
            }

            const child_process = require('child_process');
            const env = Object.assign({}, process.env, {
                NOTEBOOKLM_AUTH_JSON: sessionJson
            });

            child_process.exec('notebooklm list --json', { env: env, timeout: 10000 }, (err, stdout, stderr) => {
                const output = (stdout || '') + (stderr || '');
                if (err || output.toLowerCase().includes('not logged in') || output.toLowerCase().includes('expired')) {
                    this.statusBarItemEl.setText("⚠️ Re-auth NotebookLM");
                    this.statusBarItemEl.title = `Credentials invalid or expired. Click to launch login. Error: ${output.trim()}`;
                    this.statusBarItemEl.style.color = "var(--text-error)";
                    this.statusBarItemEl.style.cursor = "pointer";
                } else {
                    this.statusBarItemEl.setText("🧠 NotebookLM: OK");
                    this.statusBarItemEl.title = "NotebookLM session credentials valid. Click to re-authenticate if needed.";
                    this.statusBarItemEl.style.color = "var(--text-success)";
                    this.statusBarItemEl.style.cursor = "pointer";
                }
            });
        } catch (e) {
            console.error("Failed to update NotebookLM status bar:", e);
            this.statusBarItemEl.setText("⚠️ Re-auth NotebookLM");
            this.statusBarItemEl.title = `Error checking status: ${e.message}. Click to launch login.`;
            this.statusBarItemEl.style.color = "var(--text-error)";
            this.statusBarItemEl.style.cursor = "pointer";
        }
    }
}


class NotebookLMCleanupModal extends obsidian.Modal {
    constructor(app, plugin, deletedNotebooks, failedDeletions, missingArtifacts) {
        super(app);
        this.plugin = plugin;
        this.deletedNotebooks = deletedNotebooks || [];
        this.failedDeletions = failedDeletions || [];
        this.missingArtifacts = missingArtifacts || [];
    }

    onOpen() {
        const { contentEl } = this;
        contentEl.empty();
        
        // Modal Container styling
        contentEl.style.padding = '10px 20px 20px 20px';
        contentEl.style.maxWidth = '600px';

        contentEl.createEl('h2', { 
            text: 'NotebookLM Cleanup Report', 
            cls: 'cleanup-modal-title' 
        }).style.color = 'var(--text-normal)';

        const mainContainer = contentEl.createDiv({ cls: 'cleanup-modal-container' });

        // 1. Success Deletions
        if (this.deletedNotebooks.length > 0) {
            const successSection = mainContainer.createDiv();
            successSection.style.marginBottom = '20px';
            
            const successTitle = successSection.createEl('h3');
            successTitle.innerHTML = `🧹 Automatically Cleaned Up (${this.deletedNotebooks.length})`;
            successTitle.style.color = '#4caf50';
            successTitle.style.marginTop = '0';
            successTitle.style.fontSize = '1.15em';
            
            successSection.createEl('p', { 
                text: 'The following single-source notebooks had matching notes in your vault with all three artifacts already generated. They have been deleted from Google NotebookLM to save your quota:', 
                cls: 'setting-item-description' 
            }).style.marginBottom = '10px';

            const listContainer = successSection.createDiv();
            listContainer.style.backgroundColor = 'var(--background-secondary)';
            listContainer.style.border = '1px solid var(--background-modifier-border)';
            listContainer.style.borderRadius = '6px';
            listContainer.style.padding = '10px 15px';
            listContainer.style.maxHeight = '150px';
            listContainer.style.overflowY = 'auto';

            this.deletedNotebooks.forEach(title => {
                const item = listContainer.createDiv();
                item.style.fontSize = '0.9em';
                item.style.padding = '4px 0';
                item.style.borderBottom = '1px solid var(--background-modifier-border-glow)';
                item.style.color = 'var(--text-muted)';
                item.innerHTML = `✅ <strong>${title}</strong>`;
            });
        }

        // 2. Failed Deletions
        if (this.failedDeletions.length > 0) {
            const failSection = mainContainer.createDiv();
            failSection.style.marginBottom = '20px';
            
            const failTitle = failSection.createEl('h3');
            failTitle.innerHTML = `⚠️ Failed Deletions (${this.failedDeletions.length})`;
            failTitle.style.color = 'var(--text-error)';
            failTitle.style.marginTop = '0';
            failTitle.style.fontSize = '1.15em';

            const listContainer = failSection.createDiv();
            listContainer.style.backgroundColor = 'var(--background-secondary)';
            listContainer.style.border = '1px solid var(--background-modifier-border)';
            listContainer.style.borderRadius = '6px';
            listContainer.style.padding = '10px 15px';
            listContainer.style.maxHeight = '120px';
            listContainer.style.overflowY = 'auto';

            this.failedDeletions.forEach(title => {
                const item = listContainer.createDiv();
                item.style.fontSize = '0.9em';
                item.style.padding = '4px 0';
                item.style.color = 'var(--text-error)';
                item.innerHTML = `❌ <strong>${title}</strong> (Check CLI connection)`;
            });
        }

        // 3. Notes Missing Artifacts
        const missingSection = mainContainer.createDiv();
        missingSection.style.marginTop = '15px';
        
        const missingTitle = missingSection.createEl('h3');
        missingTitle.innerHTML = `📝 Notes Missing Artifacts (${this.missingArtifacts.length})`;
        missingTitle.style.marginTop = '0';
        missingTitle.style.fontSize = '1.15em';

        // Reminder Box (Premium styling, styled like a note callout)
        const reminderBox = missingSection.createDiv();
        reminderBox.style.backgroundColor = 'var(--background-secondary-alt)';
        reminderBox.style.borderLeft = '4px solid var(--text-accent)';
        reminderBox.style.borderRadius = '4px';
        reminderBox.style.padding = '12px 15px';
        reminderBox.style.marginBottom = '15px';
        reminderBox.style.fontSize = '0.9em';
        reminderBox.style.lineHeight = '1.4';
        reminderBox.innerHTML = `💡 <strong>Reminder</strong>: A fresh notebook can be generated from the URL at any time. If you do not need these artifacts, you can ignore them. The corresponding Google Notebook can be kept or deleted manually.`;

        if (this.missingArtifacts.length === 0) {
            const emptyMsg = missingSection.createEl('p', { 
                text: 'All your vault notes with linked notebooks have all 3 artifacts fully generated! No missing artifacts found.' 
            });
            emptyMsg.style.color = 'var(--text-success)';
            emptyMsg.style.fontStyle = 'italic';
            emptyMsg.style.marginTop = '10px';
        } else {
            missingSection.createEl('p', { 
                text: 'The following notes are missing some NotebookLM artifacts. Would you like to generate them now?', 
                cls: 'setting-item-description' 
            }).style.marginBottom = '12px';

            const missingList = missingSection.createDiv();
            missingList.style.maxHeight = '300px';
            missingList.style.overflowY = 'auto';
            missingList.style.border = '1px solid var(--background-modifier-border)';
            missingList.style.borderRadius = '6px';
            missingList.style.padding = '10px 15px';
            missingList.style.backgroundColor = 'var(--background-primary)';

            this.missingArtifacts.forEach(nb => {
                const item = missingList.createDiv();
                item.style.borderBottom = '1px solid var(--background-modifier-border-glow)';
                item.style.padding = '10px 0';
                item.style.display = 'flex';
                item.style.flexDirection = 'column';
                item.style.gap = '8px';

                const titleRow = item.createDiv();
                titleRow.style.display = 'flex';
                titleRow.style.justifyContent = 'space-between';
                titleRow.style.alignItems = 'center';
                
                const noteTitle = titleRow.createSpan({ text: nb.title });
                noteTitle.style.fontWeight = 'bold';
                noteTitle.style.fontSize = '0.95em';

                const noteLink = titleRow.createEl('a', { text: `Open Note 📄` });
                noteLink.style.fontSize = '0.85em';
                noteLink.style.color = 'var(--text-accent)';
                noteLink.style.cursor = 'pointer';
                noteLink.style.textDecoration = 'none';
                noteLink.onClickEvent(() => {
                    const leaf = this.app.workspace.getMostRecentLeaf();
                    const file = this.app.vault.getAbstractFileByPath(nb.relative_path || nb.file_path);
                    if (file) {
                        leaf.openFile(file);
                        this.close();
                    }
                });

                const buttonRow = item.createDiv();
                buttonRow.style.display = 'flex';
                buttonRow.style.gap = '8px';
                buttonRow.style.alignItems = 'center';
                buttonRow.style.marginTop = '4px';
                
                buttonRow.createSpan({ text: 'Generate missing:' }).style.fontSize = '0.85em';
                buttonRow.style.color = 'var(--text-muted)';

                nb.missing.forEach(art => {
                    let artLabel = art;
                    if (art === 'mind-map') artLabel = '🧠 Mind Map';
                    if (art === 'audio') artLabel = '🎙️ Podcast';
                    if (art === 'cinematic-video') artLabel = '🎬 Video';

                    const artBtn = buttonRow.createEl('button', { text: artLabel });
                    artBtn.style.padding = '2px 8px';
                    artBtn.style.fontSize = '0.8em';
                    artBtn.style.cursor = 'pointer';
                    artBtn.onClickEvent(async () => {
                        artBtn.disabled = true;
                        artBtn.style.opacity = '0.5';
                        artBtn.innerText = 'Generating...';
                        
                        await this.plugin.runArtifactGeneratorForFile(nb.file_path, art);
                    });
                });
            });
        }
        
        // Footer close button
        const footer = contentEl.createDiv();
        footer.style.marginTop = '20px';
        footer.style.display = 'flex';
        footer.style.justifyContent = 'flex-end';
        
        const closeBtn = footer.createEl('button', { text: 'Done', cls: 'mod-cta' });
        closeBtn.style.padding = '6px 20px';
        closeBtn.onClickEvent(() => {
            this.close();
        });
    }

    onClose() {
        const { contentEl } = this;
        contentEl.empty();
    }
}

class NotebookLMImportModal extends obsidian.Modal {
    constructor(app, plugin, newNotebooks, duplicateNotebooks) {
        super(app);
        this.plugin = plugin;
        this.newNotebooks = newNotebooks || [];
        this.duplicateNotebooks = duplicateNotebooks || [];
        this.selectedToImport = new Set();
    }

    onOpen() {
        const { contentEl } = this;
        contentEl.empty();
        
        contentEl.style.padding = '10px 20px 20px 20px';
        contentEl.style.maxWidth = '600px';

        contentEl.createEl('h2', { 
            text: 'Import NotebookLM Notebooks', 
            cls: 'import-modal-title' 
        }).style.color = 'var(--text-normal)';

        const mainContainer = contentEl.createDiv({ cls: 'import-modal-container' });

        if (this.newNotebooks.length > 0) {
            const newSection = mainContainer.createDiv();
            newSection.style.marginBottom = '20px';
            
            const newTitle = newSection.createEl('h3');
            newTitle.innerHTML = `✨ New Notebooks (${this.newNotebooks.length})`;
            newTitle.style.color = 'var(--text-accent)';
            newTitle.style.marginTop = '0';
            
            newSection.createEl('p', { 
                text: 'The following notebooks are not in your vault. They will be imported:', 
                cls: 'setting-item-description' 
            }).style.marginBottom = '10px';

            const listContainer = newSection.createDiv();
            listContainer.style.backgroundColor = 'var(--background-secondary)';
            listContainer.style.border = '1px solid var(--background-modifier-border)';
            listContainer.style.borderRadius = '6px';
            listContainer.style.padding = '10px 15px';
            listContainer.style.maxHeight = '150px';
            listContainer.style.overflowY = 'auto';

            this.newNotebooks.forEach(nb => {
                const item = listContainer.createDiv();
                item.style.fontSize = '0.9em';
                item.style.padding = '4px 0';
                item.style.borderBottom = '1px solid var(--background-modifier-border-glow)';
                item.innerHTML = `✅ <strong>${nb.title}</strong>`;
                this.selectedToImport.add(nb.id);
            });
        }

        if (this.duplicateNotebooks.length > 0) {
            const dupSection = mainContainer.createDiv();
            dupSection.style.marginBottom = '20px';
            
            const dupTitle = dupSection.createEl('h3');
            dupTitle.innerHTML = `⚠️ Potential Duplicates (${this.duplicateNotebooks.length})`;
            dupTitle.style.color = '#ff9800';
            dupTitle.style.marginTop = '0';

            dupSection.createEl('p', { 
                text: 'The following notebooks share a very similar title with existing notes in your vault. Select the ones you still want to import:', 
                cls: 'setting-item-description' 
            }).style.marginBottom = '10px';

            const listContainer = dupSection.createDiv();
            listContainer.style.backgroundColor = 'var(--background-secondary)';
            listContainer.style.border = '1px solid var(--background-modifier-border)';
            listContainer.style.borderRadius = '6px';
            listContainer.style.padding = '10px 15px';
            listContainer.style.maxHeight = '150px';
            listContainer.style.overflowY = 'auto';

            this.duplicateNotebooks.forEach(nb => {
                const item = listContainer.createDiv();
                item.style.fontSize = '0.9em';
                item.style.padding = '6px 0';
                item.style.borderBottom = '1px solid var(--background-modifier-border-glow)';
                item.style.display = 'flex';
                item.style.alignItems = 'center';
                item.style.gap = '10px';
                
                const checkbox = item.createEl('input', { type: 'checkbox' });
                checkbox.style.cursor = 'pointer';
                checkbox.onchange = (e) => {
                    if (e.target.checked) {
                        this.selectedToImport.add(nb.id);
                    } else {
                        this.selectedToImport.delete(nb.id);
                    }
                };
                
                const labelDiv = item.createDiv();
                labelDiv.innerHTML = `<strong>${nb.title}</strong><br><span style="font-size:0.85em; color:var(--text-muted);">${nb.reason}</span>`;
            });
        }

        const footer = contentEl.createDiv();
        footer.style.marginTop = '20px';
        footer.style.display = 'flex';
        footer.style.justifyContent = 'flex-end';
        footer.style.gap = '10px';
        
        const cancelBtn = footer.createEl('button', { text: 'Cancel' });
        cancelBtn.onClickEvent(() => {
            this.close();
        });
        
        const importBtn = footer.createEl('button', { text: 'Import Selected', cls: 'mod-cta' });
        importBtn.onClickEvent(async () => {
            importBtn.disabled = true;
            importBtn.innerText = 'Importing...';
            let importedCount = 0;
            
            const allNbs = [...this.newNotebooks, ...this.duplicateNotebooks];
            for (const nb of allNbs) {
                if (this.selectedToImport.has(nb.id)) {
                    const success = await this.plugin.createLandingPage(nb);
                    if (success) importedCount++;
                }
            }
            
            new obsidian.Notice(`Successfully imported ${importedCount} NotebookLM notebooks!`);
            this.close();
        });
    }

    onClose() {
        const { contentEl } = this;
        contentEl.empty();
    }
}

class KnowledgePipelineSettingTab extends obsidian.PluginSettingTab {
    constructor(app, plugin) {
        super(app, plugin);
        this.plugin = plugin;
    }

    display() {
        try {
            const { containerEl } = this;
            containerEl.empty();
            containerEl.createEl('h2', { text: 'Knowledge Pipeline Settings' });

            const requestWithTimeout = async (params, timeoutMs = 2500) => {
                return Promise.race([
                    obsidian.requestUrl(params),
                    new Promise((_, reject) => setTimeout(() => reject(new Error("Timeout")), timeoutMs))
                ]);
            };

            new obsidian.Setting(containerEl)
                .setName('Imports Target Folder')
                .setDesc('Folder path relative to vault root where unstructured links are imported (e.g. 00_Imports).')
                .addText(text => text
                    .setPlaceholder('00_Imports')
                    .setValue(this.plugin.settings.importsFolder)
                    .onChange(async (value) => {
                        this.plugin.settings.importsFolder = value.trim();
                        await this.plugin.saveSettings();
                    }));

            containerEl.createEl('h3', { text: 'AI Provider Settings' });

            // LLM Provider (Dropdown)
            new obsidian.Setting(containerEl)
                .setName('LLM Provider')
                .setDesc('Select the AI backend to use for generating summaries.')
                .addDropdown(dropdown => dropdown
                    .addOption('gemini', 'Gemini (Google Cloud)')
                    .addOption('ollama', 'Ollama (Local)')
                    .setValue(this.plugin.settings.llmProvider || 'gemini')
                    .onChange(async (value) => {
                        this.plugin.settings.llmProvider = value;
                        if (value === 'gemini') {
                            this.plugin.settings.llmModel = 'gemini-2.5-flash';
                        } else {
                            this.plugin.settings.llmModel = 'qwen2.5:7b';
                        }
                        await this.plugin.saveSettings();
                        this.display();
                    }));

            const provider = this.plugin.settings.llmProvider || 'gemini';

            if (provider === 'gemini') {
                containerEl.createEl('h3', { text: 'Gemini Credentials (Keychain)' });

                // Gemini API Key (Password input)
                const geminiSetting = new obsidian.Setting(containerEl)
                    .setName('Gemini API Key')
                    .setDesc('Secure Gemini API key stored in your system keychain.')
                    .addText(text => {
                        text.inputEl.type = 'password';
                        text.setPlaceholder('Enter Gemini API Key');
                        let secretId = this.plugin.settings.geminiApiKeyId;
                        if (!secretId) {
                            secretId = 'knowledge-pipeline-gemini-api-key';
                            this.plugin.settings.geminiApiKeyId = secretId;
                            this.plugin.saveSettings();
                        }
                        Promise.resolve(this.app.secretStorage.getSecret(secretId)).then(value => {
                            text.setValue(value || '');
                        });
                        text.onChange(async (value) => {
                            await this.app.secretStorage.setSecret(secretId, value.trim());
                        });
                    });

                const geminiBadge = containerEl.createEl('span');
                geminiBadge.style.display = 'inline-block';
                geminiBadge.style.width = '10px';
                geminiBadge.style.height = '10px';
                geminiBadge.style.borderRadius = '50%';
                geminiBadge.style.marginLeft = '8px';
                geminiBadge.style.verticalAlign = 'middle';
                geminiBadge.style.backgroundColor = '#8e8e93';
                geminiBadge.setAttribute('title', 'Checking...');
                geminiSetting.nameEl.appendChild(geminiBadge);

                (async () => {
                    let secretId = this.plugin.settings.geminiApiKeyId || 'knowledge-pipeline-gemini-api-key';
                    const geminiKey = await this.app.secretStorage.getSecret(secretId);
                    if (!geminiKey) {
                        geminiBadge.style.backgroundColor = '#ff453a';
                        geminiBadge.setAttribute('title', 'Missing Gemini API Key');
                        return;
                    }
                    try {
                        const res = await requestWithTimeout({
                            url: `https://generativelanguage.googleapis.com/v1beta/models?key=${geminiKey}`,
                            method: 'GET'
                        });
                        if (res.status === 200) {
                            geminiBadge.style.backgroundColor = '#30d158';
                            geminiBadge.setAttribute('title', 'Gemini API: Connected');
                        } else {
                            geminiBadge.style.backgroundColor = '#ff453a';
                            geminiBadge.setAttribute('title', 'Gemini API: Invalid Key');
                        }
                    } catch(e) {
                        geminiBadge.style.backgroundColor = '#ff453a';
                        geminiBadge.setAttribute('title', 'Gemini API: Connection Error / Timeout');
                    }
                })();
            } else {
                containerEl.createEl('h3', { text: 'Ollama Connection Settings' });

                // Ollama URL
                const ollamaSetting = new obsidian.Setting(containerEl)
                    .setName('Ollama Endpoint')
                    .setDesc('The base URL of your local Ollama server.')
                    .addText(text => text
                        .setPlaceholder('http://localhost:11434')
                        .setValue(this.plugin.settings.ollamaUrl || 'http://localhost:11434')
                        .onChange(async (value) => {
                            this.plugin.settings.ollamaUrl = value.trim();
                            await this.plugin.saveSettings();
                        }));

                const ollamaBadge = containerEl.createEl('span');
                ollamaBadge.style.display = 'inline-block';
                ollamaBadge.style.width = '10px';
                ollamaBadge.style.height = '10px';
                ollamaBadge.style.borderRadius = '50%';
                ollamaBadge.style.marginLeft = '8px';
                ollamaBadge.style.verticalAlign = 'middle';
                ollamaBadge.style.backgroundColor = '#8e8e93';
                ollamaBadge.setAttribute('title', 'Checking...');
                ollamaSetting.nameEl.appendChild(ollamaBadge);

                (async () => {
                    const ollamaUrl = this.plugin.settings.ollamaUrl || 'http://localhost:11434';
                    try {
                        const res = await requestWithTimeout({
                            url: `${ollamaUrl}/api/tags`,
                            method: 'GET'
                        });
                        if (res.status === 200) {
                            ollamaBadge.style.backgroundColor = '#30d158';
                            ollamaBadge.setAttribute('title', 'Ollama Server: Online');
                        } else {
                            ollamaBadge.style.backgroundColor = '#ff453a';
                            ollamaBadge.setAttribute('title', 'Ollama Server: Unavailable');
                        }
                    } catch(e) {
                        ollamaBadge.style.backgroundColor = '#ff453a';
                        ollamaBadge.setAttribute('title', 'Ollama Server: Offline / Timeout');
                    }
                })();
            }

            containerEl.createEl('h3', { text: 'AI Model Settings' });

            // LLM Model Selection
            const geminiOptions = ['gemini-2.5-flash', 'gemini-1.5-flash', 'gemini-2.5-pro', 'gemini-1.5-pro'];
            const ollamaOptions = ['qwen2.5:7b', 'gemma3:4b', 'llama3', 'mistral'];
            const currentOptions = provider === 'gemini' ? geminiOptions : ollamaOptions;
            
            let modelDropdownValue = this.plugin.settings.llmModel;
            if (!currentOptions.includes(modelDropdownValue) && modelDropdownValue !== 'custom') {
                modelDropdownValue = 'custom';
            }

            new obsidian.Setting(containerEl)
                .setName('AI Model')
                .setDesc('Select the model to use for generating note summaries.')
                .addDropdown(dropdown => {
                    if (provider === 'gemini') {
                        dropdown
                            .addOption('gemini-2.5-flash', 'Gemini 2.5 Flash')
                            .addOption('gemini-1.5-flash', 'Gemini 1.5 Flash')
                            .addOption('gemini-2.5-pro', 'Gemini 2.5 Pro')
                            .addOption('gemini-1.5-pro', 'Gemini 1.5 Pro')
                            .addOption('custom', 'Custom...');
                    } else {
                        dropdown
                            .addOption('qwen2.5:7b', 'Qwen 2.5 7B')
                            .addOption('gemma3:4b', 'Gemma 3 4B')
                            .addOption('llama3', 'Llama 3')
                            .addOption('mistral', 'Mistral')
                            .addOption('custom', 'Custom...');
                    }

                    dropdown.setValue(modelDropdownValue)
                        .onChange(async (value) => {
                            if (value === 'custom') {
                                this.plugin.settings.llmModel = this.plugin.settings.customModel || '';
                            } else {
                                this.plugin.settings.llmModel = value;
                            }
                            await this.plugin.saveSettings();
                            this.display();
                        });
                });

            // Custom Model name input
            if (modelDropdownValue === 'custom') {
                new obsidian.Setting(containerEl)
                    .setName('Custom Model Identifier')
                    .setDesc('Type the exact model identifier (e.g. llama3:8b).')
                    .addText(text => text
                        .setPlaceholder('Enter model identifier')
                        .setValue(this.plugin.settings.customModel || '')
                        .onChange(async (value) => {
                            this.plugin.settings.customModel = value.trim();
                            this.plugin.settings.llmModel = value.trim();
                            await this.plugin.saveSettings();
                        }));
            }

            const notebookHeader = containerEl.createEl('h3', { text: 'NotebookLM CLI Authentication' });
            const notebookBadge = containerEl.createEl('span');
            notebookBadge.style.display = 'inline-block';
            notebookBadge.style.width = '10px';
            notebookBadge.style.height = '10px';
            notebookBadge.style.borderRadius = '50%';
            notebookBadge.style.marginLeft = '8px';
            notebookBadge.style.verticalAlign = 'middle';
            notebookBadge.style.backgroundColor = '#8e8e93';
            notebookBadge.setAttribute('title', 'Checking...');
            notebookHeader.appendChild(notebookBadge);

            (async () => {
                const sessionJson = await this.app.secretStorage.getSecret('knowledge-pipeline-notebooklm-session') || '';
                if (!sessionJson) {
                    notebookBadge.style.backgroundColor = '#ff453a';
                    notebookBadge.setAttribute('title', 'NotebookLM CLI: Not Logged In');
                    return;
                }
                const child_process = require('child_process');
                const env = Object.assign({}, process.env, { NOTEBOOKLM_AUTH_JSON: sessionJson });
                child_process.exec('notebooklm list --json', { env: env, timeout: 5000 }, (err, stdout, stderr) => {
                    const output = (stdout || '') + (stderr || '');
                    if (err || output.toLowerCase().includes('not logged in') || output.toLowerCase().includes('expired')) {
                        notebookBadge.style.backgroundColor = '#ff453a';
                        notebookBadge.setAttribute('title', `NotebookLM CLI: Expired / Error\n${output.trim()}`);
                    } else {
                        notebookBadge.style.backgroundColor = '#30d158';
                        notebookBadge.setAttribute('title', 'NotebookLM CLI: Connected');
                    }
                });
            })();

            // Instructions text block
            const descEl = containerEl.createDiv({ cls: 'setting-item-description' });
            descEl.innerHTML = `
                <p>The Knowledge Pipeline uses the local <code>notebooklm</code> CLI to generate mind maps, podcast audio, and cinematic videos.</p>
                <ol>
                    <li>Click the <strong>Login & Import</strong> button below. This will launch a separate console window and open a browser.</li>
                    <li>Complete the Google login in the browser window. Once successful, the session is saved automatically.</li>
                    <li>Close the command window if it does not close itself.</li>
                    <li>Obsidian will detect the completion, save the session to the secure keychain, and secure the local file.</li>
                </ol>
            `;
            descEl.style.cssText = 'margin-bottom: 1.5em; line-height: 1.4;';

            // Button Setting: Login and Import CLI Credentials to Keychain
            new obsidian.Setting(containerEl)
                .setName('Login and Import Credentials')
                .setDesc('Launches the NotebookLM login process, opens a browser for authentication, then saves the session to Obsidian\'s secure keychain.')
                .addButton(button => button
                    .setButtonText('Login & Import')
                    .setCta()
                    .onClick(async () => {
                        await this.plugin.launchLogin();
                    }));

            // Button Setting: Test CLI Connection
            new obsidian.Setting(containerEl)
                .setName('Test CLI Connection')
                .setDesc('Tests CLI status with the keychain credentials without exposing files on disk.')
                .addButton(button => button
                    .setButtonText('Test Connection')
                    .onClick(async () => {
                        try {
                            const secretId = 'knowledge-pipeline-notebooklm-session';
                            const sessionJson = await this.app.secretStorage.getSecret(secretId) || '';

                            if (!sessionJson) {
                                new obsidian.Notice("Error: No saved credentials in keychain. Please import credentials first.");
                                return;
                            }

                            new obsidian.Notice("Testing NotebookLM authentication status...");

                            const child_process = require('child_process');
                            const env = Object.assign({}, process.env, {
                                NOTEBOOKLM_AUTH_JSON: sessionJson
                            });

                            // Execute notebooklm list
                            child_process.exec('notebooklm list --json', { env: env, timeout: 10000 }, (err, stdout, stderr) => {
                                const output = (stdout || '') + (stderr || '');
                                console.log("[NotebookLM test]", output);
                                if (err || output.toLowerCase().includes('not logged in') || output.toLowerCase().includes('expired')) {
                                    new obsidian.Notice(`Connection Failed: ${output.trim()}`);
                                } else {
                                    new obsidian.Notice(`Connection Succeeded: Authorized!`);
                                }
                            });

                        } catch (err) {
                            console.error("Test connection error:", err);
                            new obsidian.Notice(`Test Connection Failed: ${err.message}`);
                        }
                    }));

            // Button Setting: Clear Keychain Credentials
            new obsidian.Setting(containerEl)
                .setName('Clear Saved Credentials')
                .setDesc('Removes the stored session from Obsidian\'s keychain.')
                .addButton(button => button
                    .setButtonText('Clear Credentials')
                    .setWarning()
                    .onClick(async () => {
                        const secretId = 'knowledge-pipeline-notebooklm-session';
                        const existing = await this.app.secretStorage.getSecret(secretId);
                        if (!existing) {
                            new obsidian.Notice("No stored credentials found to clear.");
                            return;
                        }
                        await this.app.secretStorage.setSecret(secretId, '');
                        new obsidian.Notice("Success: Saved credentials removed from system keychain!");
                    }));

            // Button Setting: NotebookLM Sync New Notebooks
            new obsidian.Setting(containerEl)
                .setName('NotebookLM Sync New Notebooks')
                .setDesc('Scans Google NotebookLM for notebooks not yet in your vault, and generates native landing pages for them.')
                .addButton(button => button
                    .setButtonText('Sync Notebooks')
                    .setCta()
                    .onClick(async () => {
                        this.plugin.runNotebookSync();
                    }));

            // Button Setting: NotebookLM Vault Cleanup
            new obsidian.Setting(containerEl)
                .setName('NotebookLM Vault Cleanup')
                .setDesc('Scans vault notes and Google Notebooks. Automatically deletes completed single-source notebooks, and prompts to generate missing artifacts.')
                .addButton(button => button
                    .setButtonText('Run Cleanup')
                    .setCta()
                    .onClick(async () => {
                        try {
                            const secretId = 'knowledge-pipeline-notebooklm-session';
                            const sessionJson = await this.plugin.app.secretStorage.getSecret(secretId) || '';

                            if (!sessionJson) {
                                new obsidian.Notice("Error: No saved credentials in keychain. Please import credentials first.");
                                return;
                            }

                            const loadingNotice = new obsidian.Notice("Scanning vault notes and Google NotebookLM CLI... please wait.", 0);

                            const child_process = require('child_process');
                            const path = require('path');
                            const fs = require('fs');

                            const vaultPath = this.app.vault.adapter.getBasePath();
                            const scriptPath = path.join(vaultPath, '.obsidian', 'plugins', 'knowledge-pipeline', 'notebooklm_cleanup.py');

                            if (!fs.existsSync(scriptPath)) {
                                loadingNotice.hide();
                                new obsidian.Notice(`Error: Cleanup script not found at ${scriptPath}`);
                                return;
                            }

                            const env = Object.assign({}, process.env, {
                                NOTEBOOKLM_AUTH_JSON: sessionJson
                            });

                            child_process.exec(`python -u "${scriptPath}"`, { env: env, timeout: 60000 }, async (err, stdout, stderr) => {
                                if (err) {
                                    loadingNotice.hide();
                                    console.error("Cleanup scan failed:", stderr || stdout);
                                    new obsidian.Notice(`Cleanup Scan Failed: ${stderr || stdout}`);
                                    return;
                                }

                                try {
                                    const report = JSON.parse(stdout.trim());
                                    
                                    if (report.error) {
                                        loadingNotice.hide();
                                        new obsidian.Notice(`Cleanup Scan Failed: ${report.error}`);
                                        return;
                                    }

                                    const cleanable = report.cleanable || [];
                                    const missing = report.missing_artifacts || [];
                                    
                                    const deletedNotebooks = [];
                                    const failedDeletions = [];

                                    if (cleanable.length > 0) {
                                        loadingNotice.setMessage(`Found ${cleanable.length} completed notebooks. Deleting from Google NotebookLM...`);
                                        
                                        // Delete in small parallel batches of 3
                                        const batchSize = 3;
                                        for (let i = 0; i < cleanable.length; i += batchSize) {
                                            const batch = cleanable.slice(i, i + batchSize);
                                            const promises = batch.map(nb => {
                                                return new Promise(resolve => {
                                                    child_process.exec(`notebooklm delete -n ${nb.notebook_id} --json`, { env: env, timeout: 10000 }, (delErr, delStdout, delStderr) => {
                                                        if (delErr) {
                                                            console.error(`Failed to delete notebook ${nb.title}:`, delStderr || delStdout);
                                                            failedDeletions.push(nb.title);
                                                        } else {
                                                            deletedNotebooks.push(nb.title);
                                                        }
                                                        resolve();
                                                    });
                                                });
                                            });
                                            await Promise.all(promises);
                                        }
                                    }
                                    
                                    loadingNotice.hide();
                                    
                                    if (deletedNotebooks.length === 0 && failedDeletions.length === 0 && missing.length === 0) {
                                        new obsidian.Notice("All notebooks are fully up-to-date with artifacts! Cleanup complete.");
                                    } else {
                                        new NotebookLMCleanupModal(this.app, this.plugin, deletedNotebooks, failedDeletions, missing).open();
                                    }
                                } catch (parseErr) {
                                    loadingNotice.hide();
                                    console.error("Failed to parse cleanup report:", stdout);
                                    new obsidian.Notice("Failed to parse cleanup scan report.");
                                }
                            });

                        } catch (err) {
                            console.error("Cleanup error:", err);
                            new obsidian.Notice(`Cleanup Failed: ${err.message}`);
                        }
                    }));
        } catch (e) {
            console.error("Knowledge Pipeline settings tab display error:", e);
            new obsidian.Notice("Settings Display Error: " + e.message);
        }
    }
}

module.exports = KnowledgePipelinePlugin;
