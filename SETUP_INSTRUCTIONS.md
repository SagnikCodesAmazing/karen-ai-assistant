# Voice Assistant Setup Instructions

## Files Created
1. `voice_assistant.py` - Main application code
2. `requirements.txt` - Python dependencies
3. `README.md` - Detailed documentation
4. `SETUP_INSTRUCTIONS.md` - This file

## Setup Steps

### 1. Install Python Dependencies
Open Command Prompt or PowerShell and run:
```bash
pip install -r requirements.txt
```

### 2. Download Vosk Model
- Go to: https://alphacephei.com/vosk/models
- Download `vosk-model-small-en-us-0.15.zip`
- Extract the contents
- Rename the extracted folder to `vosk-model-small-en-us-0.15`
- Place it in the same directory as `voice_assistant.py`

### 3. Install and Configure Ollama
1. Download Ollama from: https://ollama.com
2. Install Ollama (it will run as a service)
3. Open Command Prompt and run:
   ```bash
   ollama pull llama3
   ```
4. Keep Ollama running (it should start automatically as a service)

### 4. Optional: Enable Porcupine Wake Word (Recommended for Better Accuracy)
1. Get a free access key from https://picovoice.ai/
2. Edit `voice_assistant.py`:
   - Set `USE_PORCUPINE = True`
   - Replace `"YOUR_PVPORCUNE_ACCESS_KEY"` with your actual key
3. You'll need to generate wake word files using Picovoice console (or use built-in ones)

### 5. Run the Assistant
```bash
python voice_assistant.py
```

## Usage
- The assistant will appear in your system tray
- In the current demo version, make a loud sound (clap, snap) to wake it
- Speak your command clearly after the wake sound
- Example commands:
  - "Open notepad"
  - "Search for latest AI news"
  - "What is the weather like today?"
  - "Open chrome"

## How to Customize
- **Applications:** Edit the `app_map` dictionary in `open_application()` function
- **Wake Word:** For production use, implement proper Porcupine wake word detection
- **Responses:** Modify the Ollama prompts in `process_command()` function
- **TTS:** Adjust rate, volume, and voice in `initialize_tts()` function

## Troubleshooting
- **Module not found errors:** Run `pip install -r requirements.txt` again
- **Vosk model errors:** Verify the model folder is named correctly and in the right location
- **Ollama connection errors:** Make sure Ollama is running (`ollama serve` in terminal)
- **Microphone issues:** Check Windows microphone permissions and settings
- **No sound:** Check system volume and TTS engine configuration

## Notes
- This is a demonstration version with energy-based wake detection
- For better wake word accuracy, implement Porcupine properly
- First responses may be slower as Ollama loads the model
- All processing is done locally for privacy and low latency
- Say "exit" or use the system tray icon to quit the application

## Extending the Assistant
The modular design makes it easy to add new capabilities:
1. Add new intent types in the command processing logic
2. Implement new action functions (like sending emails, setting reminders, etc.)
3. Enhance the natural language understanding with more sophisticated prompts
4. Add context awareness for multi-turn conversations

Enjoy your voice assistant!