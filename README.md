# JARVIS_Voice_Assistant [Just A Rather Very Intelligent System]

Windows-first setup (autostart, tray, frozen build): **`docs/WINDOWS.md`**. Admin / UAC & safety: **`docs/WINDOWS_ADMIN.md`**. Sandboxed file/open/delete tools: **`docs/FILE_TOOLS.md`**.

[![forthebadge made-with-python](http://ForTheBadge.com/images/badges/made-with-python.svg)](https://www.python.org/)

- This repository consist of **Voice Assistant** of Iron Man [aka Tony Stark from Marvel Movies].

- To be Honest, it's Not as **Intelligent** as in the movie, but it can do a lot of cool things and Automate your daily tasks you do on your personal computers.

<p align="center">
  <img src="/images/JARVIS_AI.jpg" width="700" alt="JARVIS-AI">
</p>

## 📹 Video Demonstration

<p align="center"><a href="https://vimeo.com/562670975">LIVE DEMO LINK</a></p>

## 🤔 Required Packages

- Modular installs: **`requirements-core.txt`**, **`requirements-brain.txt`**, **`requirements-rag.txt`**, **`requirements-shell.txt`** (microphone / freeze notes in **`docs/WINDOWS.md`**).

- You can copy paste the Below Mentioned Code to Install all the Packages

```
pip install pyttsx3
pip install SpeechRecognition
pip install pipwin
pipwin install pyaudio
pip install pywhatkit
pip install PyAutoGUI
pip install wolframalpha
pip install wikipedia
pip install git+https://github.com/abenassi/Google-Search-API
pip install playsound
pip install speedtest-cli
pip install psutil
pip install pyjokes
```

## ✨ All Task that Can be Performed by Jarvis

### 1) Open any Application

✔️ It can Open any Application like Notepad, Command Prompt, Visual Studio Code, YouTube in Chrome and any Possible Application once you understand the Logic.

```
🎤 "open notepad"
🎤 "open command prompt"
🎤 "open code"
🎤 "open youtube"
```

### 2) Play Music or Particular Music

✔️ It can Play Random or Specific Music on YouTube [Can also be Modified for Local Music Files] 
```
🎤 "play music"
🎤 "play mozart"
```
### 3) Increase / Decrease the Speakers Volume

✔️ It can Change [increase, decrease or mute] the System Volume 
```
🎤 "volume up"
🎤 "volume down"
🎤 "volume mute"
```
### 4) Opens any System App [For Eg: Calculator]

✔️ For Example, Calculator can be Opened using Below Command. It can be Modified for Any System Apps.
```
🎤 "open calculator"
```
### 5) Tells about something, by searching on the internet

✔️ It Opens Google in Chrome and Ask User for Search Query, Get Information about Particular Person, & search in Wikipedia.
```
🎤 "open google"
🎤 "who is"
🎤 "wikipedia"
```
### 6) Tells the weather for a place

✔️ Using Openweather API, We can get the Temperature and Description of Climate of Particular City.
```
🎤 "weather"
```
### 7) Tells the current time and date

✔️ It can tell the Current Time and Date to User
```
🎤 "time"
🎤 "date"
```
### 8) Set an Alarm

✔️ Set an Alarm for User [Still in Development]
```
🎤 "alarm"
```
### 9) Tell the Internet Speed

✔️ Tells the Download and Upload Speed in MBPS
```
🎤 "internet speed"
```
### 10) Internet Connection

✔️ Check if you're Connected to Internet
```
🎤 "internet connection"
```
### 11) Daily News

✔️ Speaks Out Daily News from News API
```
🎤 "news"
```
### 12) Spell a Particular Word

✔️ For Example, computer -> "c o m p u t e r"
```
🎤 "spell"
```
### 13) How much Memory Consumed

✔️ Tells How much Memory is Used in this Processes
```
🎤 "memory" 
```
### 14) Calculate

✔️ Helps to Do some Small Handy Calculations
```
🎤 "calculate"
```
### 15) Help

✔️ Tells all the Task that can be Performed using JARVIS
```
🎤 "help"
```
### 16) Jokes

✔️ It randomly Generates Jokes to the User
```
🎤 "jokes"
```
### 17) Author

✔️ It Tells the Person who Made JARVIS [Inspired from ROBOT Movie]
```
🎤 "who made you"
🎤 "who created you"
```
### 18) exit

✔️ To Exit the Voice Assistant
```
🎤 "exit"
```
## Local knowledge base (RAG)

Index `.txt` / `.md` files under **`knowledge_docs/`** (or set **`JARVIS_KNOWLEDGE_DIR`**). Install extras:

```bash
pip install -r requirements-rag.txt
```

Speak a knowledge phrase (see `knowledge/voice_triggers.py`).

**Vector store**

- **`JARVIS_VECTOR_BACKEND`** — `chroma` (default) uses `data/jarvis_chroma/`. **`postgres`** (or **`pg`**, **`postgresql`**) stores vectors in Postgres with **pgvector**.

**Postgres backend**

Use a Postgres image that includes pgvector (e.g. **`pgvector/pgvector:pg16`**). Configure:

```bash
export JARVIS_VECTOR_BACKEND=postgres
export DATABASE_URL=postgresql://USER:PASSWORD@HOST:5432/DATABASE
# or POSTGRES_HOST, POSTGRES_PORT, POSTGRES_DB, POSTGRES_USER, POSTGRES_PASSWORD
```

Example Docker:

```bash
docker run -e POSTGRES_PASSWORD=test -p 5432:5432 pgvector/pgvector:pg16
```

Switching **Chroma ↔ Postgres** triggers a **full re-index** (tracked via `data/kb_vector_backend.marker`, gitignored locally). **Embedding dimension:** if you change the embedding model (`OPENAI_EMBEDDING_MODEL`, `ST_MODEL_NAME`, etc.), reset the DB chunk table or **`TRUNCATE kb_chunks, kb_documents`** — the **`vector(dim)`** column dimension must match **`JARVIS_EMBEDDING_DIMENSION`** when you set overrides.

### Richer indexing (optional)

- **`JARVIS_CHUNK_MAX_CHARS`** — larger/smaller text chunks when embedding (default **900** via `knowledge/fs_index.py`).
- **URL capture:** the conversational brain can save a page under **`knowledge_docs/_ingested_urls/`** (`knowledge/url_ingest.py`), then call **resync** so RAG picks up the new file.

## Conversational brain (OpenAI tools) + episodic memory

Copy **`.env.template`** to **`.env`**, fill in keys (never commit `.env`). Optional: `pip install python-dotenv` so variables load automatically when supported by the tooling you use.

- **`JARVIS_BRAIN_PERSONA`** — `jarvis` (default, British-butler briefing) or `friday` (calm ops-chief, “Boss” first). Synonyms **`ops`** / **`chief`** use the FRIDAY preset. Set **`JARVIS_BRAIN_SYSTEM_PROMPT`** to a full custom system string to override either preset entirely.

Phrases that **do not** match the hard-coded shortcuts fall through to **`jarvis_brain.py`**: an OpenAI Chat Completions agent with **tools** (browser, Wikipedia, YouTube, apps, volume, local RAG sync, URL ingest, “remember” notes).

```bash
pip install -r requirements-brain.txt
export OPENAI_API_KEY=...
# optional explicit enable (already default when key is set):
export JARVIS_BRAIN=1   # use 0 / false / off to disable

# tuning
export OPENAI_CHAT_MODEL=gpt-4o-mini
export JARVIS_BRAIN_TOOL_ROUNDS=6
```

**Episodic memory** (prior turns + tool-stored notes) feeds the next inference:

| Storage | When |
|---------|------|
| **Postgres** | `DATABASE_URL` or `POSTGRES_HOST`+`POSTGRES_DB` (+ user/password vars) — table `jarvis_episodic_memory`. |
| **SQLite** (default if no Postgres) | `data/jarvis_memory.sqlite` |

**Env:**

- **`JARVIS_MEMORY_BACKEND`** — `auto`, `postgres`, or `sqlite`
- **`JARVIS_MEMORY_LINES`** — how many past rows (~24 default) approximate into the prompt

## 🤝 Contributing

+ We encourage you to contribute to JARVIS for Further Improvement!
+ Feel free to Fork this project and Make your Own changes too
+ Please check out the [Contributing guide](/CONTRIBUTING.md) for guidelines about how to proceed.
+ For major changes, please open an issue first to discuss what you would like to change.

## 🥺 License

You are Free to Use the Above Code for Educational Purpose.
