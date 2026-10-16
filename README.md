# Voice Assistant - Jarvis/Edith Style

A voice assistant with extremely low latency designed to perform simple tasks like opening applications. Uses local LLM via Ollama for understanding and generating responses.

## Features
- Wake word activation (sound-based trigger in this demo version)
- Speech-to-text using Vosk (offline, low latency)
- Natural language understanding using Ollama (local LLM)
- Text-to-speech using pyttsx3
- System tray application that runs in background
- Can open applications, search web, and answer questions
- Designed for extensibility

## Requirements
- Windows 10/11 (should work on other OS with minor modifications)
- Python 3.7+
- Microphone
- Ollama installed and running ([https://ollama.com](https://ollama.com))

## Installation

1. **Install Python dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

2. **Download Vosk model:**
   - Download `vosk-model-small-en-us-0.15` from [https://alphacephei.com/vosk/models](https://alphacephei.com/vosk/models)
   - Extract the folder to the same directory as `voice_assistant.py`
   - Rename the extracted folder to `vosk-model-small-en-us-0.15` (if not already)

3. **Install and run Ollama:**
   - Download and install Ollama from [https://ollama.com](https://ollama.com)
   - Pull a language model (recommend llama3 for good balance of speed and quality):
     ```bash
     ollama pull llama3
     ```
   - Start Ollama server:
     ```bash
     ollama serve
     ```
   - Keep the Ollama server running in the background

4. **Optional: For better wake word detection**
   - Get a free access key from [Picovoice](https://picovoice.ai/)
   - Replace `YOUR_PVPORCUNE_ACCESS_KEY` in the code with your actual key
   - Set `USE_PORCUPINE = True` in the configuration
   - Generate wake word files using Picovoice console

## Usage
1. Run the assistant:
   ```bash
   python voice_assistant.py
   ```
2. The application will appear in your system tray
3. In this demo version, make a loud sound (like clapping) to wake the assistant
4. Speak your command after the wake sound
5. Examples of commands:
   - "Open notepad"
   - "Search for chocolate cake recipes"
   - "What is the capital of France?"
   - "Open chrome"

## How It Works
1. **Wake Detection:** Listens for audio energy exceeding a threshold (demo version)
2. **Speech Recognition:** Uses Vosk to convert speech to text offline
3. **Natural Language Understanding:** Sends text to Ollama to determine intent
4. **Action Execution:** Performs the requested action (open app, search, etc.)
5. **Response:** Uses Ollama to generate a natural language response and speaks it

## Extending the Assistant
- Add more application mappings in the `open_application` function
- Add more intent types in the `process_command` function
- Improve wake word detection by implementing Porcupine properly
- Add more sophisticated command handling

## Notes
- This is a demo version with sound-based wake detection. For production, implement proper wake word detection.
- The assistant keeps Ollama loaded in memory for fast responses after initial load.
- First command may be slower as Ollama loads the model.
- All speech processing is done locally for privacy and low latency.

## Troubleshooting
- **Vosk model not found:** Make sure you downloaded and extracted the model correctly
- **Ollama connection error:** Make sure Ollama server is running (`ollama serve`)
- **No sound from TTS:** Check your system volume and TTS engine settings
- **Microphone not working:** Check microphone permissions and settings in Windows