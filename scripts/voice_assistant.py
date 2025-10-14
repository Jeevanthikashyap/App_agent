# C:/Users/50105636/Documents/AppAgent/scripts/voice_assistant.py
import google.generativeai as genai # MODIFIED: Import Google's library
from gtts import gTTS
import speech_recognition as sr
from playsound import playsound
import os,time
import re
import sounddevice as sd
import numpy as np
import soundfile as sf
import whisper
from pathlib import Path
# --- Configuration ---
from config import load_config
from utils import print_with_color
configs = load_config()
# MODIFIED: Configure the Google client instead of OpenAI
try:
    genai.configure(api_key="google api key/openai api key")
except KeyError:
    print("ERROR: GOOGLE_API_KEY not found in config.json. Please add it.")
    exit()

# Setup the specific model we want to use
model = genai.GenerativeModel(model_name="models/gemini-2.5-flash") # Use the powerful and fast Flash model

OUTPUT_LOG_FILE = "output.txt"
USER_INPUT_FILE = "input.txt"
# ---------------------
def clean_text_for_llm(raw_text):
    """Removes ANSI escape codes for cleaner processing."""
    ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
    return ansi_escape.sub('', raw_text)

def summarize_log_and_get_question():
    """Reads the log, finds the last agent request, and summarizes the context."""
    if not os.path.exists(OUTPUT_LOG_FILE):
        return "Log file not found.", "No question found."

    with open(OUTPUT_LOG_FILE, "r", encoding='utf-8') as f:
        log_content = f.read()

    clean_log = clean_text_for_llm(log_content)

    # Find the very last "AGENT REQUEST" in the log
    lines = clean_log.strip().split('\n')
    last_question = "I need the initial task description." # Default for the first run
    for line in reversed(lines):
        if line.startswith("AGENT REQUEST:"):
            last_question = line.replace("AGENT REQUEST:", "").strip()
            break
        if "Please provide the task description..." in line:
            # This handles the very first run before any agent requests
            last_question = "What is the task you want me to perform?"
            break

    try:
        # === MODIFIED: This entire block is replaced to use Gemini ===
        prompt = f"""The following is a log from an autonomous agent. Summarize the agent's last few actions in one brief, conversational sentence to provide context for the user.
        Do not mention file names or technical details.

        LOG:
        {clean_log}
        """
        # The 'generate_content' method is used for Gemini
        response = model.generate_content(prompt)
        summary = response.text
        # =============================================================
    except Exception as e:
        print(f"LLM Summarization failed: {e}")
        summary = "The agent is waiting for your instruction."

    return summary, last_question

def speak_text(text):
    """Converts text to speech and plays it."""
    try:
        print(f"\nASSISTANT SPEAKING: {text}")
        tts = gTTS(text=text, lang='en')
        audio_file = "assistant_voice.mp3"
        tts.save(audio_file)
        time.sleep(3)  # Give it a moment to save
        playsound(audio_file)
        os.remove(audio_file)
        open(OUTPUT_LOG_FILE, "w").close()
    except Exception as e:
        print(f"Text-to-speech failed: {e}")


def speak_summary_only():
    summary, _ = summarize_log_and_get_question()
    speak_text(summary)

def listen_for_voice():
    """Listens for user's voice and returns the text."""
    duration = 10
    device = 15
    fs = 44100
    channels = 2

    print(f"Recording your response from microphone {device}...")
    speak_text("start telling your input")
    audio = sd.rec(int(duration * fs), samplerate=fs, channels=channels, dtype='int16', device=device)
    sd.wait()
    print("Recording complete.")

    wav_path = Path('input.wav')
    sf.write(wav_path.as_posix(), audio, fs)
    print(f"Audio saved to: {wav_path}")

    try:
        print("Loading Whisper model (base)...")
        model = whisper.load_model("base")
        print("Transcribing audio...")
        result = model.transcribe(wav_path.as_posix())
        text = result.get("text", "").strip()
        print(f"Transcribed text: {text}")
        return text
    except Exception as e:
        print(f"Transcription failed: {e}")
        return ""

def main():
    """Main voice interaction loop."""
    # 1. Summarize and find the question
    summary, question = summarize_log_and_get_question()

    # 2. Speak to the user
    full_speech_text = f"{summary}. {question}"
    speak_text(full_speech_text)

    # 3. Listen for the response
    user_response = None
    while not user_response:
        user_response = listen_for_voice()
        if not user_response:
            speak_text("I didn't catch that. Please try again.")

    # 4. Write the response to input.txt
    with open(USER_INPUT_FILE, "w", encoding='utf-8') as f:
        f.write(user_response)

    print(f"\nSuccessfully wrote '{user_response}' to {USER_INPUT_FILE}.")
    # MODIFIED: Removed the final spoken confirmation as it's not needed with the subprocess call.
    # The main script will confirm the loaded task.
    print("Voice interaction complete. Returning control to the main agent.")


if __name__ == "__main__":
     main()