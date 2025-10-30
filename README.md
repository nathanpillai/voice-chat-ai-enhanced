# Voice Chat AI Enhanced - Docker Fixed Version 
> **Note**: This is a modified version of [bigsk1/voice-chat-ai](https://github.com/bigsk1/voice-chat-ai) that works with Docker.
created from the voice-chat-ai - this code works on local version of ollama in cpu mode without hardware and without any OpenAI api.

## Quick Start:
1. Clone original repo: `git clone https://github.com/bigsk1/voice-chat-ai`
2. Copy files from `Code/` to overwrite originals
3. Run with Docker as usual

## Fixed Pages:
- ✅ Enhanced Browser v3
- ✅ WebRTC Realtime v2 (Ollama)
- ✅ WebRTC Realtime (OpenAI) - this is the original version I kept for comparison - works well with SSL & NPM settings
- ✅ Dashboard

🛠️ Modified Files

This version includes changes to the following files:

app/main.py

app/app.py

app/shared.py

app/transcription.py

app/enhanced_logic.py

cli.py

app/requirements.txt

app/requirements_cpu.txt

templates/enhanced_browser_v3.html

templates/webrtc_realtime_v2.html

templates/index.html

templates/webrtc_realtime.html

static/js/scripts.js

static/js/enhanced.js

static/js/webrtc_realtime_v2.js

## Future Plans:
- Remove dependency on original source
- Standalone installation

<img width="717" height="797" alt="image" src="https://github.com/user-attachments/assets/d357b2c0-64cf-4227-a88a-67a74d54fda8" />

<img width="1904" height="713" alt="image" src="https://github.com/user-attachments/assets/06b0d1ef-80f5-49ec-a6e3-3b83f9b8d14d" />

