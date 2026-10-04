import sounddevice as sd
import numpy as np
import keyboard
import pyperclip
import time
from faster_whisper import WhisperModel

# ---- SETTINGS ----
samplerate = 16000
model_size = "base"  # same model we tested, works great

# ---- LOAD AI MODEL (once, at startup) ----
print("Loading Whisper model... please wait.")
model = WhisperModel(model_size, device="cpu", compute_type="int8")
print("Model loaded! Ready to use.")
print("Press CTRL+1 to START recording, CTRL+2 to STOP and transcribe.")
print("Press CTRL+C in this terminal to quit the app.")

recording = []
is_recording = False

def callback(indata, frames, time_info, status):
    """This runs automatically while recording, collecting audio chunks."""
    if is_recording:
        recording.append(indata.copy())

# Start the microphone stream (always listening, but only saves when is_recording=True)
stream = sd.InputStream(samplerate=samplerate, channels=1, dtype='int16', callback=callback)
stream.start()

def start_recording():
    global is_recording, recording
    recording = []  # clear previous recording
    is_recording = True
    print("\n🎤 Recording started... speak now!")

def stop_recording():
    global is_recording
    is_recording = False
    print("⏹️ Recording stopped. Transcribing...")

    if len(recording) == 0:
        print("No audio captured, try again.")
        return

    # Combine all recorded chunks into one array
    audio_data = np.concatenate(recording, axis=0)
    audio_float = audio_data.astype(np.float32) / 32768.0  # normalize for Whisper
    audio_float = audio_float.flatten()

    # Transcribe
    segments, info = model.transcribe(audio_float, beam_size=5)
    text = " ".join([segment.text for segment in segments]).strip()

    print(f"📝 Transcribed: {text}")

    if text:
        # Copy to clipboard and paste it automatically
        pyperclip.copy(text)
        time.sleep(0.1)
        keyboard.send('ctrl+v')
        print("✅ Text pasted!")
    else:
        print("⚠️ No speech detected.")

# ---- HOTKEYS ----
keyboard.add_hotkey('ctrl+1', start_recording)
keyboard.add_hotkey('ctrl+2', stop_recording)

# Keep the program running forever (until you press Ctrl+C in terminal)
keyboard.wait()