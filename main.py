# All Packages to Import

# pip install pyttsx3
# pip install SpeechRecognition
# pip install pipwin
# pipwin install pyaudio
# pip install pywhatkit
# pip install PyAutoGUI
# pip install wolframalpha
# pip install wikipedia
# pip install git+https://github.com/abenassi/Google-Search-API
# pip install playsound
# pip install speedtest-cli
# pip install psutil
# pip install pyjokes

# Python Test to Speech Package
import operator
import sys
import threading
import traceback
from typing import Optional

import pyttsx3
# Package to Recognise the Speech
import speech_recognition as sr
from speech_recognition.exceptions import WaitTimeoutError
# For Date and Time
import datetime
# For Opening the Applications
import os
# Open any Website
import webbrowser
# To Play Song on YouTube
import pywhatkit
# To Increase/Decrease the System Volume
import pyautogui
# For Opening any System Application [Calculator]
from subprocess import call
import subprocess
import shutil
from urllib.parse import quote_plus
# For Searching Anything
import wolframalpha
# For Searching Something in Wikipedia
import wikipedia
# For Searching via Google API
import googleapi
from googleapi import google
# For Weather
import requests
import json
# For Internet Speed
import speedtest
# For Internet Availibility
import urllib.request
# For Memory Usage
import psutil
# For Jokes
import pyjokes
# For Delay
import time

import elevenlabs_tts

from jarvis_exceptions import JarvisExitRequest
from knowledge.voice_triggers import extract_kb_question, wants_knowledge_lookup

try:
    from knowledge.rag_store import answer_from_knowledge, sync_knowledge_folder
    _RAG_AVAILABLE = True
except ImportError:
    _RAG_AVAILABLE = False

try:
    import jarvis_brain as jb
except ImportError:
    jb = None  # type: ignore[assignment, misc]

_tls = threading.local()


def register_voice_ui_hooks(*, on_listening=None, on_heard=None) -> None:
    """Optional callbacks for a GUI shell (set from the same thread that runs the voice loop)."""
    if on_listening or on_heard:
        _tls.voice_hooks = {"on_listening": on_listening, "on_heard": on_heard}
    elif hasattr(_tls, "voice_hooks"):
        del _tls.voice_hooks


# Voice Initialization Part for Jarvis

# Helps in synthesis and recognition of voice.
# sapi5 is Windows-only; macOS uses nsss (NSSpeechSynthesizer); Linux typically uses espeak.
if sys.platform == "win32":
    engine = pyttsx3.init("sapi5")
elif sys.platform == "darwin":
    engine = pyttsx3.init("nsss")
else:
    engine = pyttsx3.init()
voices = engine.getProperty("voices")
# print(voices[0].id) # [0 -> David, 1 -> Zira]
if voices:
    engine.setProperty("voice", voices[0].id)
    _vsub = os.environ.get("JARVIS_PYTTSX3_VOICE_SUBSTRING", "").strip()
    if _vsub:
        _low = _vsub.lower()
        for v in voices:
            blob = f"{getattr(v, 'name', '')} {getattr(v, 'id', '')}".lower()
            if _low in blob:
                engine.setProperty("voice", v.id)
                break

# Function to Convert Text to Speech
# Chain (unless JARVIS_USE_LOCAL_TTS=1): ElevenLabs → Microsoft neural (edge-tts, online) → pyttsx3 offline.
# Use your ElevenLabs cloned voice: set ELEVENLABS_API_KEY and ELEVENLABS_VOICE_ID
# (optional: ELEVENLABS_MODEL_ID, ELEVENLABS_OUTPUT_FORMAT, ELEVENLABS_API_BASE).
# Optional .env in project root is read if python-dotenv is installed.
# Free neural online: pip install edge-tts; JARVIS_EDGE_TTS_VOICE=en-US-AriaNeural (see edge-tts --list-voices).
# Offline Windows: install better SAPI voices in Settings; optional JARVIS_PYTTSX3_VOICE_SUBSTRING=David
# Set JARVIS_USE_LOCAL_TTS=1 to force pyttsx3 only.
# Set JARVIS_ELEVENLABS_ONLY=1 when ElevenLabs is configured — no other fallbacks on success path.


def speak(text):
    print("Command: " + text)
    force_local = os.environ.get("JARVIS_USE_LOCAL_TTS", "").lower() in ("1", "true", "yes")
    eleven_only = os.environ.get("JARVIS_ELEVENLABS_ONLY", "").lower() in ("1", "true", "yes")
    if not force_local and elevenlabs_tts.is_configured():
        try:
            if elevenlabs_tts.synthesize_and_play(text):
                return
        except Exception as exc:
            print(f"ElevenLabs TTS failed ({exc}).")
            if not eleven_only:
                print("Falling back to other TTS.")
        if eleven_only:
            return
    if eleven_only and not elevenlabs_tts.is_configured():
        print("JARVIS_ELEVENLABS_ONLY is set but ElevenLabs is not configured; cannot speak.")
        return

    if not force_local:
        try:
            import jarvis_edge_tts as jet

            if jet.edge_enabled() and jet.is_available():
                jet.synthesize_and_play(text)
                return
        except Exception as exc:
            print(f"Edge neural TTS failed ({exc}); using offline pyttsx3.")

    engine.say(text)
    engine.runAndWait()

def _listen_timeout_seconds():
    """Seconds to wait for speech to *begin*. None = wait indefinitely (idle until you speak)."""
    raw = os.environ.get("JARVIS_LISTEN_TIMEOUT", "").strip().lower()
    if raw in ("", "none", "inf", "infinity"):
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def _phrase_time_limit_seconds():
    raw = os.environ.get("JARVIS_PHRASE_SECONDS", "").strip()
    if raw == "":
        return 15.0
    try:
        return float(raw)
    except ValueError:
        return 15.0


# Function to Take Command [Voice] From User and Convert to text
def take_command():
    hooks = getattr(_tls, "voice_hooks", None)
    if hooks and hooks.get("on_listening"):
        hooks["on_listening"]()
    r = sr.Recognizer()
    listen_timeout = _listen_timeout_seconds()
    phrase_limit = _phrase_time_limit_seconds()
    with sr.Microphone() as source:
        if listen_timeout is None:
            print("listening… (waiting until you speak)")
        else:
            print(f"listening… (timeout {listen_timeout}s for speech to start)")
        r.pause_threshold = 1
        try:
            audio = r.listen(source, timeout=listen_timeout, phrase_time_limit=phrase_limit)
        except WaitTimeoutError:
            print("No speech detected before timeout; speak again.")
            return "none"
    try:
        print("Recognizing...")
        query = r.recognize_google(audio, language='en-in')
        print(f"user said: {query}")
        if hooks and hooks.get("on_heard"):
            hooks["on_heard"](query)
    except Exception as e:
        speak("Say that again please...")
        return "none"
    return query

# Function to Greet the User
def greet():
    hour = int(datetime.datetime.now().hour)
    if hour>=0 and hour<=12:
        speak("Good Morning Sir")
    elif hour>12 and hour<18:
        speak("Good Afternoon Sir")
    else:
        speak("Good Evening Sir")
    speak("I am your Personal Assistant Jarvis, How can I Help You Sir?")

# Function to Check if Internet Connection is Available
def connect(host='https://www.google.com/'):
    try:
        urllib.request.urlopen(host)
        return True
    except:
        return False

# Function to Read News
def News():
    # Change the API_KEY to your One

    query_params = {
        "source": "bbc-news",
        "sortBy": "top",
        "apiKey": "YOUR_API_KEY_HERE"
    }
    main_url = " https://newsapi.org/v1/articles"
    res = requests.get(main_url, params=query_params)
    open_bbc_page = res.json()
    article = open_bbc_page["articles"]
    results = []
    for ar in article:
        results.append(ar["title"])
    for i in range(len(results)):
        print(i + 1, results[i])
        speak(results[i])

# Function for Calculations
# def get_operator(op):
#     return{
#         '+': operator.add(),
#         '-': operator.sub(),
#         'x': operator.mul(),
#         'divided': operator.__truediv__(),
#         'mod': operator.mod(),
#         }[op]

def evaluate(op1, operation, op2):
    op1 = int(op1)
    op2 = int(op2)
    if(operation == '+'):
        return op1+op2
    elif(operation == '-'):
        return op1-op2
    elif (operation == 'multiply'):
        return op1*op2
    elif (operation == "divide"):
        if(op2!=0):
            return op1/op2
        else:
            speak("Divide by Zero Error")
            return -1

    # return get_operator(operation)(op1, op2)

# Voice commands often include "Jarvis", "the", etc. — normalize before matching.
_STOPWORDS = {"the", "a", "an"}

SITE_ALIASES = {
    "youtube": "https://www.youtube.com/",
    "google": "https://www.google.com/",
    "gmail": "https://mail.google.com/",
    "github": "https://github.com/",
}


def normalize_voice_query(q: str) -> str:
    if not q or q.strip().lower() == "none":
        return "none"
    q = q.lower().strip()
    for noise in ("hey jarvis", "hey", "jarvis", "please", "can you", "okay", "ok"):
        q = q.replace(noise, " ")
    parts = [p for p in q.split() if p not in _STOPWORDS]
    return " ".join(parts)


def wants_site(q: str, site_kw: str) -> bool:
    """Match open youtube / open the youtube / go to youtube / launch youtube."""
    if site_kw not in q:
        return False
    if f"open {site_kw}" in q or f"launch {site_kw}" in q or f"start {site_kw}" in q:
        return True
    if f"go to {site_kw}" in q or f"visit {site_kw}" in q:
        return True
    if f"to {site_kw}" in q and any(x in q for x in ("go", "take me", "take me to")):
        return True
    return False


def try_open_website(query: str) -> bool:
    for site, url in SITE_ALIASES.items():
        if wants_site(query, site):
            speak(f"Opening {site}")
            webbrowser.open(url)
            return True
    return False





def process_command(query: str, voice_raw: Optional[str] = None) -> None:
    """Handle one normalized voice command (must not be 'none').
    ``voice_raw`` is the verbatim (often lower-cased) transcript for episodic memory.
    """
    # All Task that Can be Performed by Jarvis

    # 1) Open websites (uses default browser — works on macOS; old code forced broken Windows Chrome path)
    if try_open_website(query):
        pass

    # 1b) Open common apps (cross-platform)
    elif "open notepad" in query or ("notepad" in query and "open" in query):
        speak("Opening text editor")
        if sys.platform == "win32":
            os.startfile("C:\\WINDOWS\\system32\\notepad.exe")
        elif sys.platform == "darwin":
            subprocess.run(["open", "-a", "TextEdit"], check=False)
        elif shutil.which("gedit"):
            subprocess.run(["gedit"], check=False)
        elif shutil.which("mousepad"):
            subprocess.run(["mousepad"], check=False)

    elif "open command prompt" in query or "open terminal" in query or (
        "terminal" in query and "open" in query
    ):
        speak("Opening terminal")
        if sys.platform == "win32":
            os.system("start cmd")
        elif sys.platform == "darwin":
            subprocess.run(["open", "-a", "Terminal"], check=False)
        else:
            for term in ("x-terminal-emulator", "gnome-terminal", "konsole", "kitty"):
                if shutil.which(term):
                    subprocess.run([term], check=False)
                    break

    elif (
        "open code" in query
        or "open vscode" in query
        or "open vs code" in query
        or "open visual studio code" in query
    ):
        speak("Opening Visual Studio Code")
        if sys.platform == "win32":
            code_path = os.path.expanduser(
                r"~\AppData\Local\Programs\Microsoft VS Code\Code.exe"
            )
            if os.path.isfile(code_path):
                os.startfile(code_path)
            else:
                os.startfile("code")
        elif sys.platform == "darwin":
            subprocess.run(["open", "-a", "Visual Studio Code"], check=False)
        elif shutil.which("code"):
            subprocess.run(["code"], check=False)

    # 2) Play Any Random Music or Particular Music
    elif 'play' in query:
        song = query.replace('jarvis', '')
        song = song.replace('play', '')
        txt = "playing" + song
        speak(txt)
        pywhatkit.playonyt(song)

    # 3) Increase/decrease the speakers master volume
    elif 'volume up' in query:
        pyautogui.press("volumeup")
    elif 'volume down' in query:
        pyautogui.press("volumedown")
    elif 'volume mute' in query or 'mute' in query:
        pyautogui.press("volumemute")

    # 4) Opens any System App [For Eg: Calculator]
    elif "open calculator" in query or ("calculator" in query and "open" in query):
        speak("Opening calculator")
        if sys.platform == "win32":
            call(["calc.exe"])
        elif sys.platform == "darwin":
            subprocess.run(["open", "-a", "Calculator"], check=False)
        elif shutil.which("gnome-calculator"):
            subprocess.run(["gnome-calculator"], check=False)

    # 5) Tells about something, by searching on the internet
    elif (
        "search google" in query
        or "google search" in query
        or "search on google" in query
    ):
        speak("Sir, What should I search on Google?")
        cm = take_command().lower()
        cm = normalize_voice_query(cm)
        if cm and cm != "none":
            webbrowser.open(f"https://www.google.com/search?q={quote_plus(cm)}")

    elif 'who is' in query:
        name = query.replace('jarvis', '')
        name = name.replace('who is', '')
        info = wikipedia.summary(name)
        print(info)
        speak(info)

    elif 'wikipedia' in query:
        speak('searching wikipedia...')
        to_search = query.replace('jarvis', '')
        to_search = to_search.replace('wikipedia', '')
        results = wikipedia.summary(to_search, sentences=2)
        speak('According to Wikipedia, ')
        speak(results)

    elif wants_knowledge_lookup(query):
        if not _RAG_AVAILABLE:
            speak(
                "Sir, knowledge mode needs extra packages: pip install -r requirements-rag.txt."
            )
        else:
            qtopic = extract_kb_question(query)
            if len(qtopic.strip()) < 4:
                speak("What topic should I search in your knowledge documents, Sir?")
                follow = normalize_voice_query(take_command().lower())
                if follow == "none":
                    return
                qtopic = follow
            try:
                reply = answer_from_knowledge(qtopic)
            except Exception as exc:
                traceback.print_exc()
                reply = f"Sir, knowledge lookup failed: {exc}"
            speak(reply)

    #6) Tells the weather for a place
    elif 'weather' in query:
        api_key = "YOUR_WEATHER_API_KEY_HERE"
        base_url = "http://api.openweathermap.org/data/2.5/weather?"
        speak("Sir, For Which Place you want to know the Weather?")
        place = take_command().lower()
        complete_url = base_url + "appid=" + api_key + "&q=" + place
        response = requests.get(complete_url)
        x = response.json()
        if response.status_code == 200:
            y = x['main']
            current_temperature = y['temp']
            z = x['weather']
            weather_description = z[0]['description']
            t3 = "Temperature at " + place + " is " + str(current_temperature) + " Kelvin and Climate is " + str(weather_description)
            print(t3)
            speak(t3)
        else:
            speak("City Not Found Sir")

    #7) Tells the current time and/or date
    elif 'time' in query:
        time_str = datetime.datetime.now().strftime('%I:%M %p')
        t1 = "Current Time is " + time_str
        speak(t1)
    elif 'date' in query:
        from datetime import date
        today = date.today()
        d2 = today.strftime("%B %d, %Y")
        t2 = "Today is " + d2
        print(t2)
        speak(t2)

    #8) Set an Alarm
    elif 'alarm' in query:
        speak("Sir, Please tell me the time to set the alarm, Example - set alarm for 6:30 am")
        res = take_command().lower()
        res = res.replace('set alarm for', '')
        res = res.replace('.', '')
        res = res.upper()
        print(res)
        import MyAlarm
        MyAlarm.alarm(res)

    #9) Tell the Internet Speed
    elif 'internet speed' in query:
        st = speedtest.Speedtest()
        download_speed = str(round(float(st.download()/1000000)))
        upload_speed = str(round(float(st.upload()/1000000)))
        t5 = f"Sir, You Internet Connection has {download_speed} mega byte per seconds Downloading Speed and {upload_speed} mega byte per second Uploading Speed."
        print(t5)
        speak(t5)

    #10) Internet Connection
    elif 'internet connection' in query:
        if connect()==True:
            msg1 = "Internet Connection Available Sir"
            print(msg1)
            speak(msg1)
        else:
            msg2 = "Internet Connection Not Available Sir"
            print(msg2)
            speak(msg2)

    #11) Tell the Daily News
    elif 'news' in query:
        News()

    #12) Spell a Particular Word
    elif 'spell' in query:
        speak("Sir, Please tell me the word to Spell")
        res = take_command().lower()
        for i in res:
            speak(i)

    #13) How much Memory Consumed
    elif 'memory' in query:
        process = psutil.Process(os.getpid())
        msg3 = "Memory Consumed by your computer is " + str(process.memory_info()[0]/1000000) + " Mega bytes"
        print(msg3)
        speak(msg3)

    #14) Calculate
    elif 'calculate' in query:
        speak("What do you want to calculate? Example : 5 plus 10")
        res = take_command().lower()
        msg6 = evaluate(*(res.split(" ")))
        t7 = "Your Result is " + str(msg6)
        print(t7)
        speak(t7)

    # 15) help
    elif 'help' in query:
        speak('I can Help you to Open an Application Play Music, Search for Something, Tell you Time, Date, News, Internet Connection and Speed, Memory Consumptiom and much more.')

    #16) Jokes
    elif 'joke' in query or 'jokes' in query:
        msg9 = pyjokes.get_joke()
        print(msg9)
        speak(msg9)

    #17) Author
    elif "who made you" in query or "who created you" in query:
        speak("I have been created by Bhagya Rana.")

    # 18) exit
    elif 'exit' in query:
        speak("Thanks for giving me your precious time Sir")
        raise JarvisExitRequest

    else:
        if jb is not None and jb.is_brain_enabled():
            from memory.episodic_memory import memory_append_turn, memory_fetch_block

            utterance = voice_raw.strip() if voice_raw else query
            try:
                episodic_prefill = memory_fetch_block()
                reply = jb.run_agent_brain(
                    user_utterance=utterance,
                    episodic_prefill=episodic_prefill,
                )
                if reply:
                    speak(reply)
                memory_append_turn("user", utterance)
                if reply:
                    memory_append_turn("assistant", reply.strip())
            except JarvisExitRequest:
                speak("Thanks for giving me your precious time Sir")
                raise
            except Exception:
                traceback.print_exc()
                speak("Sir, the reasoning engine hit an error trying that phrase.")
            return

        speak(
            "Sir, nothing in the shorthand command list matched. "
            "Set OPENAI_API_KEY so the conversational brain can take flexible requests "
            "(pip install -r requirements-brain.txt), or phrase it closer to a built-in command."
        )


def run_voice_session(
    *,
    do_greet: bool = True,
    stop_event: Optional[threading.Event] = None,
    on_listening=None,
    on_heard=None,
) -> None:
    """
    Main voice loop. Use jarvis_shell for fullscreen UI + login replacement path.
    """
    try:
        if on_listening or on_heard:
            register_voice_ui_hooks(on_listening=on_listening, on_heard=on_heard)
        if _RAG_AVAILABLE:
            try:
                n_chunks = sync_knowledge_folder()
                if n_chunks:
                    print(f"Knowledge base: indexed {n_chunks} text chunks.", flush=True)
            except Exception:
                traceback.print_exc()
                print("Knowledge base: sync failed (install requirements-rag.txt).", flush=True)
        if do_greet:
            greet()
        while stop_event is None or not stop_event.is_set():
            raw = take_command().lower()
            query = normalize_voice_query(raw)
            if query == "none":
                continue
            try:
                process_command(query, voice_raw=raw)
            except JarvisExitRequest:
                break
            except Exception:
                traceback.print_exc()
                speak("Something went wrong with that command Sir.")
    finally:
        register_voice_ui_hooks()


if __name__ == "__main__":
    run_voice_session()