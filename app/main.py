import json
import os
import signal
import uvicorn
import asyncio
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse
from starlette.background import BackgroundTask

# Load .env file - allows both OpenAI and Ollama to coexist
# Each page will use MODEL_PROVIDER to determine which to use
try:
    from dotenv import load_dotenv
    load_dotenv()
    print("✓ Environment variables loaded from .env file")
except ImportError:
    print("⚠ python-dotenv not installed, using system environment variables only")
    pass

from .shared import clients, set_current_character, conversation_history, add_client, remove_client
from .app_logic import start_conversation, stop_conversation, set_env_variable, save_conversation_history, characters_folder, set_transcription_model, fetch_ollama_models, load_character_prompt, save_character_specific_history
from .enhanced_logic import start_enhanced_conversation, stop_enhanced_conversation
import logging
from threading import Thread
import uuid
import aiohttp
import shutil




def center_banner(banner_text: str) -> str:
    terminal_width = shutil.get_terminal_size((80, 20)).columns  # fallback = 80
    centered_lines = []
    for line in banner_text.splitlines():
        centered_line = line.center(terminal_width)
        centered_lines.append(centered_line)
    return "\n".join(centered_lines)

def display_banner():
    raw_banner = f"""

 ▌ ▐·      ▪   ▄▄· ▄▄▄ .     ▄▄·  ▄ .▄ ▄▄▄· ▄▄▄▄▄     ▄▄▄· ▪  
▪█·█▌▪     ██ ▐█ ▌▪▀▄.▀·    ▐█ ▌▪██▪▐█▐█ ▀█ •██      ▐█ ▀█ ██ 
▐█▐█• ▄█▀▄ ▐█·██ ▄▄▐▀▀▪▄    ██ ▄▄██▀▐█▄█▀▀█  ▐█.▪    ▄█▀▀█ ▐█·
 ███ ▐█▌.▐▌▐█▌▐███▌▐█▄▄▌    ▐███▌██▌▐▀▐█ ▪▐▌ ▐█▌·    ▐█ ▪▐▌▐█▌
. ▀   ▀█▄▀▪▀▀▀·▀▀▀  ▀▀▀     ·▀▀▀ ▀▀▀ · ▀  ▀  ▀▀▀      ▀  ▀ ▀▀▀

"""
    print(center_banner(raw_banner))

# Configure logging
logging.basicConfig(level=logging.INFO, 
                    format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Display banner
display_banner()

app = FastAPI()

# Mount static files and templates
app.mount("/app/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/", response_class=HTMLResponse)
async def get_index(request: Request):
    # Simple landing page - no variables needed
    return templates.TemplateResponse("index.html", {
        "request": request
    })


# @app.get("/", response_class=HTMLResponse)
# async def get_index(request: Request):
#     model_provider = os.getenv("MODEL_PROVIDER")
#     character_name = os.getenv("CHARACTER_NAME", "wizard") 
#     tts_provider = os.getenv("TTS_PROVIDER")
#     openai_tts_voice = os.getenv("OPENAI_TTS_VOICE")
#     openai_model = os.getenv("OPENAI_MODEL")
#     ollama_model = os.getenv("OLLAMA_MODEL")
#     voice_speed = os.getenv("VOICE_SPEED")
#     elevenlabs_voice = os.getenv("ELEVENLABS_TTS_VOICE")
#     kokoro_voice = os.getenv("KOKORO_TTS_VOICE")
#     faster_whisper_local = os.getenv("FASTER_WHISPER_LOCAL", "true").lower() == "true"

#     return templates.TemplateResponse("index.html", {
#         "request": request,
#         "model_provider": model_provider,
#         "character_name": character_name,
#         "tts_provider": tts_provider,
#         "openai_tts_voice": openai_tts_voice,
#         "openai_model": openai_model,
#         "ollama_model": ollama_model,
#         "voice_speed": voice_speed,
#         "elevenlabs_voice": elevenlabs_voice,
#         "kokoro_voice": kokoro_voice,
#         "faster_whisper_local": faster_whisper_local,
#     })

@app.get("/characters")
async def get_characters():
    if not os.path.exists(characters_folder):
        logger.warning(f"Characters folder not found: {characters_folder}")
        return {"characters": ["Assistant"]}  # fallback
    
    try:
        character_dirs = [d for d in os.listdir(characters_folder) 
                        if os.path.isdir(os.path.join(characters_folder, d))]
        if not character_dirs:
            logger.warning("No character folders found")
            return {"characters": ["Assistant"]}  # fallback
        return {"characters": character_dirs}
    except Exception as e:
        logger.error(f"Error listing characters: {e}")
        return {"characters": ["Assistant"]}  # fallback in case of error

@app.get("/elevenlabs_voices")
async def get_elevenlabs_voices():
    project_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    voices_file = os.path.join(project_dir, 'elevenlabs_voices.json')
    example_file = os.path.join(project_dir, 'elevenlabs_voices.json.example')
    
    # If the elevenlabs_voices.json file doesn't exist but the example does, create from example
    if not os.path.exists(voices_file) and os.path.exists(example_file):
        try:
            logger.info("elevenlabs_voices.json not found. Creating from example file.")
            with open(example_file, 'r', encoding='utf-8') as src:
                with open(voices_file, 'w', encoding='utf-8') as dst:
                    dst.write(src.read())
            logger.info("Created elevenlabs_voices.json from example file.")
        except Exception as e:
            logger.error(f"Error creating elevenlabs_voices.json: {e}")
            
    # If file still doesn't exist, create a minimal version
    if not os.path.exists(voices_file):
        try:
            logger.info("Creating minimal elevenlabs_voices.json.")
            default_content = {
                "voices": {},
                "_comment": "This is a placeholder file. Replace with your own voice IDs from ElevenLabs."
            }
            with open(voices_file, 'w', encoding='utf-8') as f:
                json.dump(default_content, f, indent=2)
            logger.info("Created minimal elevenlabs_voices.json file.")
        except Exception as e:
            logger.error(f"Error creating minimal elevenlabs_voices.json: {e}")
            return {"voices": []}
    
    try:
        with open(voices_file, 'r', encoding='utf-8') as f:
            voices = json.load(f)
        return voices
    except Exception as e:
        logger.error(f"Error reading elevenlabs_voices.json: {e}")
        return {"voices": []}

@app.get("/enhanced", response_class=HTMLResponse)
async def get_enhanced(request: Request):
    return templates.TemplateResponse("enhanced.html", {"request": request})

@app.get("/enhanced_browser", response_class=HTMLResponse)
async def get_enhanced_browser(request: Request):
    """Browser Audio Mode - 100% Free Operation"""
    return templates.TemplateResponse("enhanced_browser.html", {"request": request})

@app.get("/enhanced_browser_v2", response_class=HTMLResponse)
async def get_enhanced_browser_v2(request: Request):
    """Browser Audio Mode V2 - Configurable Providers"""
    return templates.TemplateResponse("enhanced_browser_v2.html", {"request": request})

@app.get("/enhanced_browser_v3", response_class=HTMLResponse)
async def get_enhanced_browser_v3(request: Request):
    """Browser Audio Mode V3 - Live Editing"""
    return templates.TemplateResponse("enhanced_browser_v3.html", {"request": request})

@app.get("/api/character/{character_name}/prompts")
async def get_character_prompts(character_name: str):
    """Load character system prompt and mood prompts"""
    try:
        # Load system prompt
        character_prompt_file = os.path.join(characters_folder, character_name, f"{character_name}.txt")
        system_prompt = ""
        try:
            with open(character_prompt_file, 'r', encoding='utf-8') as f:
                system_prompt = f.read()
        except Exception as e:
            print(f"Error loading character prompt: {e}")
            system_prompt = "You are a helpful AI assistant."
        
        # Load mood prompts
        mood_prompts = {}
        character_prompts_path = os.path.join(characters_folder, character_name, 'prompts.json')
        try:
            if os.path.exists(character_prompts_path):
                with open(character_prompts_path, 'r', encoding='utf-8') as f:
                    mood_prompts = json.load(f)
        except Exception as e:
            print(f"Error loading mood prompts: {e}")
        
        return {
            "system_prompt": system_prompt,
            "mood_prompts": mood_prompts
        }
    except Exception as e:
        print(f"Error in get_character_prompts: {e}")
        return {
            "system_prompt": "You are a helpful AI assistant.",
            "mood_prompts": {}
        }

@app.get("/enhanced_defaults")
async def get_enhanced_defaults():
    from .enhanced_logic import enhanced_voice, enhanced_model, enhanced_tts_model, enhanced_transcription_model
    from .shared import get_current_character
    
    return {
        "character": get_current_character(),
        "voice": enhanced_voice,
        "model": enhanced_model,
        "tts_model": enhanced_tts_model,
        "transcription_model": enhanced_transcription_model
    }

@app.post("/set_character")
async def set_character(request: Request):
    try:
        data = await request.json()
        character = data.get("character")
        if not character:
            return {"status": "error", "message": "Character name is required"}
        
        # Import the set_character function from app_logic
        from .app_logic import set_api_character
        from pydantic import BaseModel
        
        # Create a model for the function
        class CharacterModel(BaseModel):
            character: str
        
        # Call the function with the character model
        result = await set_api_character(CharacterModel(character=character))
        return result
    except Exception as e:
        print(f"Error setting character: {e}")
        return {"status": "error", "message": str(e)}

@app.post("/start_conversation")
async def start_conversation_route():
    Thread(target=lambda: asyncio.run(start_conversation())).start()
    return {"status": "started"}

@app.post("/stop_conversation")
async def stop_conversation_route():
    await stop_conversation()
    return {"status": "stopped"}

@app.post("/start_enhanced_conversation")
async def start_enhanced_conversation_route(request: Request):
    data = await request.json()
    character = data.get("character")
    speed = data.get("speed")
    model = data.get("model")
    voice = data.get("voice")
    tts_model = data.get("ttsModel")
    transcription_model = data.get("transcriptionModel")
    
    asyncio.create_task(start_enhanced_conversation(
        character=character,
        speed=speed,
        model=model,
        voice=voice,
        ttsModel=tts_model,
        transcriptionModel=transcription_model
    ))
    
    return {"status": "started"}

@app.post("/stop_enhanced_conversation")
async def stop_enhanced_conversation_route():
    await stop_enhanced_conversation()
    return {"status": "stopped"}

@app.post("/clear_history")
async def clear_history():
    """Clear the conversation history."""
    try:
        # Import with alias to avoid potential shadowing issues
        from .shared import conversation_history, get_current_character as get_character
        
        current_character = get_character()
        
        # Check if this is a story or game character
        is_story_character = current_character.startswith("story_") or current_character.startswith("game_")
        print(f"Clearing history for {current_character} ({is_story_character=})")
        
        # Clear the in-memory history
        conversation_history.clear()
        
        if is_story_character:
            # Clear character-specific history file
            character_dir = os.path.join(characters_folder, current_character)
            history_file = os.path.join(character_dir, "conversation_history.txt")
            
            if os.path.exists(history_file):
                os.remove(history_file)
                print(f"Deleted character-specific history file for {current_character}")
            
            # Write empty history to character-specific file
            save_character_specific_history(conversation_history, current_character)
        else:
            # Clear global history file
            history_file = "conversation_history.txt"
            if os.path.exists(history_file):
                os.remove(history_file)
                print(f"Deleted global history file")
            
            # Write empty history to global file
            save_conversation_history(conversation_history)
        
        return {"status": "cleared"}
    except Exception as e:
        print(f"Error clearing history: {e}")
        return {"status": "error", "message": str(e)}

@app.get("/download_history")
async def download_history():
    # Create a temporary file with a unique name different from the main history file
    temp_file = f"temp_download_{uuid.uuid4().hex}.txt"
    
    # Format it the same way as the save_conversation_history function in app.py
    with open(temp_file, "w", encoding="utf-8") as file:
        for message in conversation_history:
            role = message["role"].capitalize()
            content = message["content"]
            file.write(f"{role}: {content}\n")
    
    # Return the file and ensure it will be cleaned up after sending
    return FileResponse(
        temp_file,
        media_type="text/plain",
        filename="conversation_history.txt",
        background=BackgroundTask(lambda: os.remove(temp_file) if os.path.exists(temp_file) else None)
    )

@app.get("/download_enhanced_history")
async def download_enhanced_history():
    """Download the conversation history."""
    try:
        # Import with alias to avoid potential shadowing issues
        from .shared import get_current_character as get_character
        
        current_character = get_character()
        
        # Check if this is a story or game character
        is_story_character = current_character.startswith("story_") or current_character.startswith("game_")
        print(f"Downloading history for {current_character} ({is_story_character=})")
        
        if is_story_character:
            # Get from character-specific history file
            character_dir = os.path.join(characters_folder, current_character)
            history_file = os.path.join(character_dir, "conversation_history.txt")
            
            if not os.path.exists(history_file) or os.path.getsize(history_file) == 0:
                # Create an empty history file if it doesn't exist
                with open(history_file, "w", encoding="utf-8") as f:
                    f.write(f"No conversation history found for {current_character}.\n")
                
            # Generate download filename based on character
            download_filename = f"{current_character}_history.txt"
            
            return FileResponse(
                history_file,
                media_type="text/plain",
                filename=download_filename
            )
        else:
            # Get from global history file
            history_file = "conversation_history.txt"
            
            if not os.path.exists(history_file) or os.path.getsize(history_file) == 0:
                # Create an empty history file if it doesn't exist
                with open(history_file, "w", encoding="utf-8") as f:
                    f.write("No conversation history found.\n")
            
            return FileResponse(
                history_file,
                media_type="text/plain",
                filename="conversation_history.txt"
            )
    except Exception as e:
        print(f"Error downloading history: {e}")
        return PlainTextResponse(f"Error downloading history: {str(e)}", status_code=500)

@app.post("/set_transcription_model")
async def update_transcription_model(request: Request):
    data = await request.json()
    model_name = data.get("model")
    if not model_name:
        return {"status": "error", "message": "Model name is required"}
    
    return set_transcription_model(model_name)

@app.get("/ollama_models")
async def get_ollama_models():
    """
    Fetch available models from Ollama
    """
    return await fetch_ollama_models()

@app.get("/openai_ephemeral_key")
async def get_openai_ephemeral_key():
    """
    Generate an ephemeral key for OpenAI API access from the browser
    
    In a production environment, you would use a service like Supabase or a proper server-side
    authentication system. For simplicity in this demo, we're just returning the API key directly.
    """
    try:
        # Get the API key from environment
        api_key = os.getenv("OPENAI_API_KEY")
        
        if not api_key:
            logger.error("OPENAI_API_KEY not set in environment")
            return {"error": "API key not configured"}
        
        # In a real application, you might want to create a temporary token or session
        # For this demo, we'll just return the key directly
        # WARNING: This exposes your API key in production!
        
        # Add logging to help debug
        logger.info(f"Returning ephemeral key (first 5 chars): {api_key[:5]}...")
        
        # Return in the exact format expected by the WebRTC client
        return {
            "client_secret": {
                "value": api_key
            }
        }
    except Exception as e:
        logger.error(f"Error generating ephemeral key: {e}")
        return {"error": str(e)}

@app.post("/openai_realtime_proxy")
async def proxy_openai_realtime(request: Request):
    """
    Proxy endpoint to relay WebRTC connection to OpenAI API.
    This avoids CORS issues when connecting directly from the browser.
    """
    try:
        # Get the API key
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            return HTTPException(status_code=500, detail="OpenAI API key not configured")
        
        # Get the SDP from the request body
        body = await request.body()
        sdp = body.decode('utf-8')
        
        # Get the model parameter from query params or default from environment
        default_model = os.getenv("OPENAI_REALTIME_MODEL", "gpt-4o-realtime-preview-2024-12-17")
        model = request.query_params.get('model', default_model)
        
        # Log the request (without the full SDP for privacy)
        logger.info(f"Proxying WebRTC connection to OpenAI Realtime API for model: {model}")
        
        # Forward to OpenAI
        import httpx
        
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"https://api.openai.com/v1/realtime?model={model}",
                content=sdp,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/sdp",
                    "OpenAI-Beta": "realtime=v1"
                }
            )
            
            # Return the same status code and content
            from fastapi.responses import Response
            return Response(
                content=response.content,
                status_code=response.status_code,
                media_type="application/sdp"
            )
    
    except Exception as e:
        logger.error(f"Error proxying to OpenAI: {e}")
        return HTTPException(status_code=500, detail=f"Error proxying to OpenAI: {str(e)}")


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    add_client(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            message = json.loads(data)
            if message["action"] == "stop":
                await stop_conversation()
            elif message["action"] == "start":
                selected_character = message["character"]
                await stop_conversation()  # Ensure any running conversation stops
                set_current_character(selected_character)
                await start_conversation()
            elif message["action"] == "set_character":
                set_current_character(message["character"])
                await websocket.send_json({"message": f"Character: {message['character']}"})
            elif message["action"] == "set_provider":
                set_env_variable("MODEL_PROVIDER", message["provider"])
            elif message["action"] == "set_tts":
                set_env_variable("TTS_PROVIDER", message["tts"])
            elif message["action"] == "set_openai_voice":
                set_env_variable("OPENAI_TTS_VOICE", message["voice"])
            elif message["action"] == "set_openai_model":
                set_env_variable("OPENAI_MODEL", message["model"])
            elif message["action"] == "set_ollama_model":
                set_env_variable("OLLAMA_MODEL", message["model"])
            elif message["action"] == "set_xai_model":
                set_env_variable("XAI_MODEL", message["model"])
            elif message["action"] == "set_anthropic_model":
                set_env_variable("ANTHROPIC_MODEL", message["model"])
            elif message["action"] == "set_voice_speed":
                set_env_variable("VOICE_SPEED", message["speed"])
            elif message["action"] == "set_elevenlabs_voice":
                set_env_variable("ELEVENLABS_TTS_VOICE", message["voice"])
            elif message["action"] == "set_kokoro_voice":
                set_env_variable("KOKORO_TTS_VOICE", message["voice"])
            elif message["action"] == "clear":
                conversation_history.clear()
                await websocket.send_json({"message": "Conversation history cleared."})
    except WebSocketDisconnect:
        remove_client(websocket)
        logger.info(f"Client disconnected from standard websocket")
    except Exception as e:
        logger.error(f"Error in standard websocket: {e}")
        # Still remove the client to prevent resource leaks
        remove_client(websocket)

@app.websocket("/ws_enhanced")
async def websocket_enhanced_endpoint(websocket: WebSocket):
    await websocket.accept()
    
    # Add client to the list
    add_client(websocket)
    print(f"Enhanced WebSocket client {id(websocket)} connected")
    logging.info("connection open")
    
    # Notify client they are connected successfully
    try:
        await websocket.send_json({"action": "connected"})
    except:
        pass
    
    try:
        # Process messages from the client
        while True:
            data = await websocket.receive_text()
            try:
                message = json.loads(data)
                if message.get("action") == "ping":
                    # Respond to heartbeats
                    await websocket.send_json({"action": "pong"})
            except json.JSONDecodeError:
                # Not a JSON message
                pass
                
    except WebSocketDisconnect:
        logging.info("Client disconnected from enhanced websocket")
    except Exception as e:
        logging.error(f"Error in enhanced websocket: {e}")
    finally:
        # Remove client from the list on any error or disconnect
        remove_client(websocket)
        print(f"Enhanced WebSocket client {id(websocket)} disconnected")

@app.websocket("/ws_enhanced_browser")
async def websocket_enhanced_browser_endpoint(websocket: WebSocket):
    """WebSocket endpoint for browser-based audio recording (100% free operation)"""
    await websocket.accept()
    
    # Add client to the list
    add_client(websocket)
    print(f"Enhanced Browser WebSocket client {id(websocket)} connected")
    logging.info("Browser audio connection open")
    
    # Import necessary functions
    from .enhanced_logic import (
        transcribe_browser_audio, 
        enhanced_chat_completion, 
        enhanced_chat_completion_ollama,  # ← ADD THIS LINE
        enhanced_text_to_speech,
        load_character_prompt,
        sanitize_response,
        analyze_mood,
        characters_folder,
        MAX_CHAR_LENGTH
    )
    from .shared import get_current_character, conversation_history
    
    # Track conversation state
    is_active = False
    
    try:
        # Notify client they are connected successfully
        await websocket.send_json({"action": "connected", "message": "Browser audio mode ready"})
        
        # Process messages from the client
        while True:
            # Receive either text (JSON) or bytes (audio)
            print(f"DEBUG: Waiting for WebSocket message... (is_active={is_active})")
            message = await websocket.receive()
            print(f"DEBUG: Received message - type: {type(message)}, keys: {list(message.keys())}")

            # Handle disconnects explicitly to avoid Starlette receive errors
            if message.get('type') == 'websocket.disconnect':
                code = message.get('code')
                print(f"DEBUG: WebSocket disconnect received (code={code}). Exiting loop.")
                break
            
            if 'text' in message:
                print(f"DEBUG: Text message received: {message['text'][:100]}")
                # Handle JSON commands
                try:
                    data = json.loads(message['text'])
                    action = data.get('action')
                    
                    if action == 'start_conversation':
                        # Guard against duplicate starts
                        if is_active:
                            await websocket.send_json({
                                "action": "error",
                                "message": "Conversation already active"
                            })
                            continue
                        
                        # Start conversation with browser audio mode
                        character = data.get('character')
                        if character:
                            set_current_character(character)
                        
                        # Clear old conversation history
                        from .shared import clear_conversation_history
                        clear_conversation_history()
                        
                        is_active = True
                        await websocket.send_json({
                            "action": "conversation_started",
                            "message": f"Started conversation with {get_current_character()}"
                        })
                        print(f"Started browser audio conversation with {get_current_character()}")

                        # Generate and send an initial greeting in character
                        try:
                            current_character = get_current_character()
                            character_prompt_file = os.path.join(characters_folder, current_character, f"{current_character}.txt")
                            # Load character prompt for system message
                            try:
                                with open(character_prompt_file, 'r', encoding='utf-8') as f:
                                    base_system_message = f.read()
                            except Exception:
                                base_system_message = "You are a helpful AI assistant."

                            # Attempt to load a custom greeting from prompts.json
                            greeting_override = None
                            character_prompts_path = os.path.join(characters_folder, current_character, 'prompts.json')
                            try:
                                if os.path.exists(character_prompts_path):
                                    with open(character_prompts_path, 'r', encoding='utf-8') as f:
                                        mood_prompts = json.load(f)
                                        greeting_override = mood_prompts.get('greeting')
                            except Exception:
                                pass

                            # Create greeting text via LLM if no override
                            if greeting_override and greeting_override.strip():
                                ai_response = greeting_override.strip()
                            else:
                                ai_response = await enhanced_chat_completion(
                                    "Introduce yourself in character with a brief one-sentence greeting and a short question to begin.",
                                    base_system_message,
                                    "",
                                    None
                                )

                            ai_response = sanitize_response(ai_response)

                            # Add to conversation history and send text
                            conversation_history.append({"role": "assistant", "content": ai_response})
                            await websocket.send_json({
                                "action": "ai_message",
                                "message": ai_response
                            })

                            # Generate TTS greeting and send to the browser
                            await websocket.send_json({
                                "action": "generating_speech",
                                "message": "Generating speech..."
                            })

                            # Use OpenAI TTS for browser mode
                            try:
                                import aiohttp
                                import tempfile
                                
                                openai_api_key = os.getenv("OPENAI_API_KEY")
                                tts_voice = os.getenv("OPENAI_TTS_VOICE", "onyx")
                                tts_model = os.getenv("OPENAI_MODEL_TTS", "gpt-4o-mini-tts")
                                voice_speed = float(os.getenv("VOICE_SPEED", "1.0"))
                                
                                if not openai_api_key:
                                    raise Exception("OpenAI API key not configured")
                                
                                # Call OpenAI TTS API
                                url = "https://api.openai.com/v1/audio/speech"
                                headers = {
                                    "Authorization": f"Bearer {openai_api_key}",
                                    "Content-Type": "application/json"
                                }
                                payload = {
                                    "model": tts_model,
                                    "input": ai_response,
                                    "voice": tts_voice,
                                    "speed": voice_speed,
                                    "response_format": "wav"
                                }
                                
                                async with aiohttp.ClientSession() as session:
                                    async with session.post(url, headers=headers, json=payload) as response:
                                        if response.status == 200:
                                            audio_bytes = await response.read()
                                            await websocket.send_bytes(audio_bytes)
                                            print(f"Sent greeting audio: {len(audio_bytes)} bytes (OpenAI TTS)")
                                        else:
                                            error_text = await response.text()
                                            raise Exception(f"OpenAI TTS error: {response.status} - {error_text}")
                                
                                await websocket.send_json({
                                    "action": "response_complete",
                                    "message": "Ready for next input"
                                })
                            except Exception as e:
                                print(f"Error generating TTS greeting: {e}")
                                await websocket.send_json({
                                    "action": "error",
                                    "message": f"TTS Error: {str(e)}"
                                })
                        except Exception as e:
                            print(f"Error generating initial greeting: {e}")
                            import traceback
                            traceback.print_exc()
                        
                    elif action == 'stop_conversation':
                        is_active = False
                        # Clear conversation history
                        from .shared import clear_conversation_history
                        clear_conversation_history()
                        await websocket.send_json({
                            "action": "conversation_stopped",
                            "message": "Conversation stopped"
                        })
                        
                    elif action == 'ping':
                        await websocket.send_json({"action": "pong"})
                        
                except json.JSONDecodeError as e:
                    print(f"Error parsing JSON: {e}")
                    
            elif 'bytes' in message:
                print(f"DEBUG: Binary message received! Size: {len(message['bytes'])} bytes, is_active: {is_active}")
                if not is_active:
                    print(f"DEBUG: Ignoring audio because is_active=False")
                    await websocket.send_json({
                        "action": "conversation_stopped",
                        "message": "Conversation stopped - ignoring audio"
                    })
                    continue
                    
                # Handle binary audio data from browser
                audio_data = message['bytes']
                print(f"Received audio data: {len(audio_data)} bytes")
                
                try:
                    # Notify client we're processing
                    await websocket.send_json({
                        "action": "processing",
                        "message": "Transcribing..."
                    })
                    
                    # Check environment for which transcription to use
                    use_local = os.getenv("FASTER_WHISPER_LOCAL", "true").lower() == "true"
                    
                    # Transcribe the audio
                    transcription = await transcribe_browser_audio(audio_data, use_local_whisper=use_local)
                    
                    if not transcription or transcription.strip() == "":
                        await websocket.send_json({
                            "action": "error",
                            "message": "No speech detected. Please try again."
                        })
                        continue
                    
                    print(f"Transcription: {transcription}")
                    
                    # Send transcription to client
                    await websocket.send_json({
                        "action": "user_message",
                        "message": f"You: {transcription}"
                    })
                    
                    # Add to conversation history
                    conversation_history.append({"role": "user", "content": transcription})
                    
                    # Get character info
                    current_character = get_current_character()
                    character_prompt_file = os.path.join(characters_folder, current_character, f"{current_character}.txt")
                    
                    # Load character prompt
                    try:
                        with open(character_prompt_file, 'r', encoding='utf-8') as f:
                            base_system_message = f.read()
                    except:
                        base_system_message = "You are a helpful AI assistant."
                    
                    # Analyze mood
                    detected_mood = analyze_mood(transcription)
                    
                    # Get mood prompt
                    mood_prompt = ""
                    character_prompts_path = os.path.join(characters_folder, current_character, 'prompts.json')
                    try:
                        if os.path.exists(character_prompts_path):
                            with open(character_prompts_path, 'r', encoding='utf-8') as f:
                                mood_prompts = json.load(f)
                                mood_prompt = mood_prompts.get(detected_mood, "")
                    except:
                        pass
                    
                    # Get AI response
                    await websocket.send_json({
                        "action": "ai_thinking",
                        "message": "Thinking..."
                    })
                    
                    # Check MODEL_PROVIDER to use Ollama or OpenAI
                    model_provider = os.getenv("MODEL_PROVIDER", "openai").lower()

                    if model_provider == "ollama":
                        ai_response = await enhanced_chat_completion_ollama(
                            transcription,
                            base_system_message,
                            mood_prompt,
                            conversation_history[:-1] if len(conversation_history) > 1 else None
                        )
                    else:
                        ai_response = await enhanced_chat_completion(
                            transcription,
                            base_system_message,
                            mood_prompt,
                            conversation_history[:-1] if len(conversation_history) > 1 else None
                    )
                    
                    # Clean up response
                    ai_response = sanitize_response(ai_response)
                    
                    # Add to history
                    conversation_history.append({"role": "assistant", "content": ai_response})
                    
                    # Manage history size
                    if current_character.startswith("story_") or current_character.startswith("game_"):
                        if len(conversation_history) > 100:
                            conversation_history[:] = conversation_history[-100:]
                    else:
                        if len(conversation_history) > 30:
                            conversation_history[:] = conversation_history[-30:]
                    
                    # Send AI response text
                    await websocket.send_json({
                        "action": "ai_message",
                        "message": ai_response
                    })
                    
                    # Generate and send TTS audio
                    await websocket.send_json({
                        "action": "generating_speech",
                        "message": "Generating speech..."
                    })
                    
                    # Generate audio with OpenAI TTS and send to browser
                    try:
                        import aiohttp
                        
                        openai_api_key = os.getenv("OPENAI_API_KEY")
                        tts_voice = os.getenv("OPENAI_TTS_VOICE", "onyx")
                        tts_model = os.getenv("OPENAI_MODEL_TTS", "gpt-4o-mini-tts")
                        voice_speed = float(os.getenv("VOICE_SPEED", "1.0"))
                        
                        if not openai_api_key:
                            raise Exception("OpenAI API key not configured")
                        
                        # Call OpenAI TTS API
                        url = "https://api.openai.com/v1/audio/speech"
                        headers = {
                            "Authorization": f"Bearer {openai_api_key}",
                            "Content-Type": "application/json"
                        }
                        payload = {
                            "model": tts_model,
                            "input": ai_response,
                            "voice": tts_voice,
                            "speed": voice_speed,
                            "response_format": "wav"
                        }
                        
                        async with aiohttp.ClientSession() as session:
                            async with session.post(url, headers=headers, json=payload) as response:
                                if response.status == 200:
                                    audio_bytes = await response.read()
                                    await websocket.send_bytes(audio_bytes)
                                    print(f"Sent {len(audio_bytes)} bytes of audio to browser (OpenAI TTS)")
                                else:
                                    error_text = await response.text()
                                    raise Exception(f"OpenAI TTS error: {response.status} - {error_text}")
                                    
                    except Exception as e:
                        print(f"Error generating audio: {e}")
                        import traceback
                        traceback.print_exc()
                        await websocket.send_json({
                            "action": "error",
                            "message": f"TTS Error: {str(e)}"
                        })

                    # Notify done
                    await websocket.send_json({
                        "action": "response_complete",
                        "message": "Ready for next input"
                    })
                    
                except Exception as e:
                    print(f"Error processing audio: {e}")
                    import traceback
                    traceback.print_exc()
                    await websocket.send_json({
                        "action": "error",
                        "message": f"Error: {str(e)}"
                    })
                
    except WebSocketDisconnect:
        logging.info("Client disconnected from enhanced browser websocket")
    except Exception as e:
        logging.error(f"Error in enhanced browser websocket: {e}")
        import traceback
        traceback.print_exc()
    finally:
        # Remove client from the list on any error or disconnect
        remove_client(websocket)
        print(f"Enhanced Browser WebSocket client {id(websocket)} disconnected")

@app.websocket("/ws_enhanced_browser_v2")
async def websocket_enhanced_browser_v2_endpoint(websocket: WebSocket):
    """WebSocket endpoint for browser-based audio recording V2 - Configurable providers"""
    await websocket.accept()
    
    # Add client to the list
    add_client(websocket)
    print(f"Enhanced Browser V2 WebSocket client {id(websocket)} connected")
    logging.info("Browser audio V2 connection open")
    
    # Import necessary functions
    from .enhanced_logic import (
        transcribe_browser_audio, 
        enhanced_chat_completion,
        enhanced_chat_completion_ollama,
        load_character_prompt,
        sanitize_response,
        analyze_mood,
        characters_folder,
        MAX_CHAR_LENGTH
    )
    from .shared import get_current_character, set_current_character, conversation_history
    
    # Track conversation state and configuration
    is_active = False
    config = {
        'modelProvider': 'ollama',
        'model': 'llama3.2',
        'ttsProvider': 'openai',
        'voice': 'onyx',
        'speed': '1.0'
    }
    
    try:
        # Notify client they are connected successfully
        await websocket.send_json({"action": "connected", "message": "Browser audio V2 mode ready"})
        
        # Process messages from the client
        while True:
            message = await websocket.receive()

            # Handle disconnects
            if message.get('type') == 'websocket.disconnect':
                code = message.get('code')
                print(f"DEBUG: WebSocket disconnect received (code={code}). Exiting loop.")
                break
            
            if 'text' in message:
                # Handle JSON commands
                try:
                    data = json.loads(message['text'])
                    action = data.get('action')
                    
                    if action == 'start_conversation':
                        # Guard against duplicate starts
                        if is_active:
                            await websocket.send_json({
                                "action": "error",
                                "message": "Conversation already active"
                            })
                            continue
                        
                        # Store configuration
                        character = data.get('character')
                        if character:
                            set_current_character(character)
                        
                        config['modelProvider'] = data.get('modelProvider', 'ollama')
                        config['model'] = data.get('model', 'llama3.2')
                        config['ttsProvider'] = data.get('ttsProvider', 'openai')
                        config['voice'] = data.get('voice', 'onyx')
                        config['speed'] = data.get('speed', '1.0')
                        
                        # Clear old conversation history
                        from .shared import clear_conversation_history
                        clear_conversation_history()
                        
                        is_active = True
                        await websocket.send_json({
                            "action": "conversation_started",
                            "message": f"Started with {config['modelProvider']} + {config['ttsProvider']}"
                        })
                        print(f"Started browser audio V2 conversation with {get_current_character()}")
                        print(f"Config: {config}")
                        
                        # Generate greeting (similar to original enhanced_browser)
                        try:
                            # Get character info
                            current_character = get_current_character()
                            character_prompt_file = os.path.join(characters_folder, current_character, f"{current_character}.txt")
                            
                            # Load character prompt
                            try:
                                with open(character_prompt_file, 'r', encoding='utf-8') as f:
                                    base_system_message = f.read()
                            except Exception:
                                base_system_message = "You are a helpful AI assistant."
                            
                            # Check for custom greeting in prompts.json
                            greeting_override = None
                            character_prompts_path = os.path.join(characters_folder, current_character, 'prompts.json')
                            try:
                                if os.path.exists(character_prompts_path):
                                    with open(character_prompts_path, 'r', encoding='utf-8') as f:
                                        mood_prompts = json.load(f)
                                        greeting_override = mood_prompts.get('greeting')
                            except Exception:
                                pass
                            
                            # Create greeting text
                            if greeting_override and greeting_override.strip():
                                ai_response = greeting_override.strip()
                            else:
                                # Use configured LLM for greeting
                                if config['modelProvider'] == 'ollama':
                                    os.environ['OLLAMA_MODEL'] = config['model']
                                    ai_response = await enhanced_chat_completion_ollama(
                                        "Introduce yourself in character with a brief one-sentence greeting and a short question to begin.",
                                        base_system_message,
                                        "",
                                        None
                                    )
                                else:
                                    if config['modelProvider'] == 'openai':
                                        os.environ['MODEL_PROVIDER'] = 'openai'
                                        os.environ['OPENAI_MODEL'] = config['model']
                                    elif config['modelProvider'] == 'anthropic':
                                        os.environ['MODEL_PROVIDER'] = 'anthropic'
                                        os.environ['ANTHROPIC_MODEL'] = config['model']
                                    elif config['modelProvider'] == 'xai':
                                        os.environ['MODEL_PROVIDER'] = 'xai'
                                        os.environ['XAI_MODEL'] = config['model']
                                    
                                    ai_response = await enhanced_chat_completion(
                                        "Introduce yourself in character with a brief one-sentence greeting and a short question to begin.",
                                        base_system_message,
                                        "",
                                        None
                                    )
                            
                            ai_response = sanitize_response(ai_response)
                            
                            # Add to conversation history
                            conversation_history.append({"role": "assistant", "content": ai_response})
                            
                            # Send text to client
                            await websocket.send_json({
                                "action": "ai_message",
                                "message": ai_response
                            })
                            
                            # Generate TTS greeting
                            await websocket.send_json({
                                "action": "generating_speech",
                                "message": "Generating greeting..."
                            })
                            
                            # Use configured TTS provider
                            try:
                                import aiohttp
                                
                                if config['ttsProvider'] == 'openai':
                                    openai_api_key = os.getenv("OPENAI_API_KEY")
                                    tts_voice = config['voice']
                                    tts_model = os.getenv("OPENAI_MODEL_TTS", "gpt-4o-mini-tts")
                                    voice_speed = float(config['speed'])
                                    
                                    if not openai_api_key:
                                        raise Exception("OpenAI API key not configured")
                                    
                                    # Call OpenAI TTS API
                                    url = "https://api.openai.com/v1/audio/speech"
                                    headers = {
                                        "Authorization": f"Bearer {openai_api_key}",
                                        "Content-Type": "application/json"
                                    }
                                    payload = {
                                        "model": tts_model,
                                        "input": ai_response,
                                        "voice": tts_voice,
                                        "speed": voice_speed,
                                        "response_format": "wav"
                                    }
                                    
                                    async with aiohttp.ClientSession() as session:
                                        async with session.post(url, headers=headers, json=payload) as response:
                                            if response.status == 200:
                                                audio_bytes = await response.read()
                                                await websocket.send_bytes(audio_bytes)
                                                print(f"Sent greeting audio: {len(audio_bytes)} bytes (OpenAI TTS)")
                                            else:
                                                error_text = await response.text()
                                                raise Exception(f"OpenAI TTS error: {response.status} - {error_text}")
                                else:
                                    raise Exception(f"TTS provider '{config['ttsProvider']}' not yet implemented")
                                
                                await websocket.send_json({
                                    "action": "response_complete",
                                    "message": "Ready for next input"
                                })
                                
                            except Exception as e:
                                print(f"Error generating TTS greeting: {e}")
                                await websocket.send_json({
                                    "action": "error",
                                    "message": f"TTS Greeting Error: {str(e)}"
                                })
                                
                        except Exception as e:
                            print(f"Error generating initial greeting: {e}")
                            import traceback
                            traceback.print_exc()
                        
                    elif action == 'stop_conversation':
                        is_active = False
                        # Clear conversation history
                        from .shared import clear_conversation_history
                        clear_conversation_history()
                        await websocket.send_json({
                            "action": "conversation_stopped",
                            "message": "Conversation stopped"
                        })
                        
                    elif action == 'ping':
                        await websocket.send_json({"action": "pong"})
                        
                except json.JSONDecodeError as e:
                    print(f"Error parsing JSON: {e}")
                    
            elif 'bytes' in message:
                print(f"DEBUG: Binary message received! Size: {len(message['bytes'])} bytes, is_active: {is_active}")
                if not is_active:
                    print(f"DEBUG: Ignoring audio because is_active=False")
                    await websocket.send_json({
                        "action": "conversation_stopped",
                        "message": "Conversation stopped - ignoring audio"
                    })
                    continue
                    
                # Handle binary audio data from browser
                audio_data = message['bytes']
                print(f"Received audio data: {len(audio_data)} bytes")
                
                try:
                    # Notify client we're processing
                    await websocket.send_json({
                        "action": "processing",
                        "message": "Transcribing..."
                    })
                    
                    # Check environment for which transcription to use
                    use_local = os.getenv("FASTER_WHISPER_LOCAL", "true").lower() == "true"
                    
                    # Transcribe the audio
                    transcription = await transcribe_browser_audio(audio_data, use_local_whisper=use_local)
                    
                    if not transcription or transcription.strip() == "":
                        await websocket.send_json({
                            "action": "error",
                            "message": "No speech detected. Please try again."
                        })
                        continue
                    
                    print(f"Transcription: {transcription}")
                    
                    # Send transcription to client
                    await websocket.send_json({
                        "action": "user_message",
                        "message": f"You: {transcription}"
                    })
                    
                    # Add to conversation history
                    conversation_history.append({"role": "user", "content": transcription})
                    
                    # Get character info
                    current_character = get_current_character()
                    character_prompt_file = os.path.join(characters_folder, current_character, f"{current_character}.txt")
                    
                    # Load character prompt
                    try:
                        with open(character_prompt_file, 'r', encoding='utf-8') as f:
                            base_system_message = f.read()
                    except:
                        base_system_message = "You are a helpful AI assistant."
                    
                    # Analyze mood
                    detected_mood = analyze_mood(transcription)
                    
                    # Get mood prompt
                    mood_prompt = ""
                    character_prompts_path = os.path.join(characters_folder, current_character, 'prompts.json')
                    try:
                        if os.path.exists(character_prompts_path):
                            with open(character_prompts_path, 'r', encoding='utf-8') as f:
                                mood_prompts = json.load(f)
                                mood_prompt = mood_prompts.get(detected_mood, "")
                    except:
                        pass
                    
                    # Get AI response using configured provider
                    await websocket.send_json({
                        "action": "ai_thinking",
                        "message": "Thinking..."
                    })
                    
                    # Route to appropriate LLM based on configuration
                    if config['modelProvider'] == 'ollama':
                        # Set environment variable temporarily for this request
                        os.environ['OLLAMA_MODEL'] = config['model']
                        ai_response = await enhanced_chat_completion_ollama(
                            transcription,
                            base_system_message,
                            mood_prompt,
                            conversation_history[:-1] if len(conversation_history) > 1 else None
                        )
                    elif config['modelProvider'] in ['openai', 'anthropic', 'xai']:
                        # Set environment variables temporarily for this request
                        if config['modelProvider'] == 'openai':
                            os.environ['MODEL_PROVIDER'] = 'openai'
                            os.environ['OPENAI_MODEL'] = config['model']
                        elif config['modelProvider'] == 'anthropic':
                            os.environ['MODEL_PROVIDER'] = 'anthropic'
                            os.environ['ANTHROPIC_MODEL'] = config['model']
                        elif config['modelProvider'] == 'xai':
                            os.environ['MODEL_PROVIDER'] = 'xai'
                            os.environ['XAI_MODEL'] = config['model']
                        
                        ai_response = await enhanced_chat_completion(
                            transcription,
                            base_system_message,
                            mood_prompt,
                            conversation_history[:-1] if len(conversation_history) > 1 else None
                        )
                    else:
                        ai_response = "Unsupported model provider"
                    
                    # Clean up response
                    ai_response = sanitize_response(ai_response)
                    
                    # Add to history
                    conversation_history.append({"role": "assistant", "content": ai_response})
                    
                    # Manage history size
                    if current_character.startswith("story_") or current_character.startswith("game_"):
                        if len(conversation_history) > 100:
                            conversation_history[:] = conversation_history[-100:]
                    else:
                        if len(conversation_history) > 30:
                            conversation_history[:] = conversation_history[-30:]
                    
                    # Send AI response text
                    await websocket.send_json({
                        "action": "ai_message",
                        "message": ai_response
                    })
                    
                    # Generate and send TTS audio based on configured provider
                    await websocket.send_json({
                        "action": "generating_speech",
                        "message": "Generating speech..."
                    })
                    
                    # Generate audio with configured TTS provider
                    try:
                        import aiohttp
                        
                        if config['ttsProvider'] == 'openai':
                            openai_api_key = os.getenv("OPENAI_API_KEY")
                            tts_voice = config['voice']
                            tts_model = os.getenv("OPENAI_MODEL_TTS", "gpt-4o-mini-tts")
                            voice_speed = float(config['speed'])
                            
                            if not openai_api_key:
                                raise Exception("OpenAI API key not configured")
                            
                            # Call OpenAI TTS API
                            url = "https://api.openai.com/v1/audio/speech"
                            headers = {
                                "Authorization": f"Bearer {openai_api_key}",
                                "Content-Type": "application/json"
                            }
                            payload = {
                                "model": tts_model,
                                "input": ai_response,
                                "voice": tts_voice,
                                "speed": voice_speed,
                                "response_format": "wav"
                            }
                            
                            async with aiohttp.ClientSession() as session:
                                async with session.post(url, headers=headers, json=payload) as response:
                                    if response.status == 200:
                                        audio_bytes = await response.read()
                                        await websocket.send_bytes(audio_bytes)
                                        print(f"Sent {len(audio_bytes)} bytes of audio to browser (OpenAI TTS)")
                                    else:
                                        error_text = await response.text()
                                        raise Exception(f"OpenAI TTS error: {response.status} - {error_text}")
                        
                        elif config['ttsProvider'] == 'espeak':
                            # Generate eSpeak TTS
                            outputs_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "outputs")
                            os.makedirs(outputs_dir, exist_ok=True)
                            temp_audio_path = os.path.join(outputs_dir, "browser_espeak.wav")
                            
                            from .app import espeak_text_to_speech
                            success = await espeak_text_to_speech(ai_response, temp_audio_path)
                            
                            if success and os.path.exists(temp_audio_path):
                                with open(temp_audio_path, 'rb') as f:
                                    audio_bytes = f.read()
                                await websocket.send_bytes(audio_bytes)
                                print(f"Sent {len(audio_bytes)} bytes of audio to browser (eSpeak TTS)")
                            else:
                                raise Exception("eSpeak TTS generation failed")

                        elif config['ttsProvider'] == 'coqui':
                            # Generate Coqui TTS
                            outputs_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "outputs")
                            os.makedirs(outputs_dir, exist_ok=True)
                            temp_audio_path = os.path.join(outputs_dir, "browser_coqui.wav")
                            
                            from .app import coqui_text_to_speech
                            success = await coqui_text_to_speech(ai_response, temp_audio_path)
                            
                            if success and os.path.exists(temp_audio_path):
                                with open(temp_audio_path, 'rb') as f:
                                    audio_bytes = f.read()
                                await websocket.send_bytes(audio_bytes)
                                print(f"Sent {len(audio_bytes)} bytes of audio to browser (Coqui TTS)")
                            else:
                                raise Exception("Coqui TTS generation failed")

                        else:
                            raise Exception(f"TTS provider '{config['ttsProvider']}' not yet implemented")
                                    
                    except Exception as e:
                        print(f"Error generating audio: {e}")
                        import traceback
                        traceback.print_exc()
                        await websocket.send_json({
                            "action": "error",
                            "message": f"TTS Error: {str(e)}"
                        })
                    
                    # Notify done
                    await websocket.send_json({
                        "action": "response_complete",
                        "message": "Ready for next input"
                    })
                    
                except Exception as e:
                    print(f"Error processing audio: {e}")
                    import traceback
                    traceback.print_exc()
                    await websocket.send_json({
                        "action": "error",
                        "message": f"Error: {str(e)}"
                    })
                
    except WebSocketDisconnect:
        logging.info("Client disconnected from enhanced browser V2 websocket")
    except Exception as e:
        logging.error(f"Error in enhanced browser V2 websocket: {e}")
        import traceback
        traceback.print_exc()
    finally:
        # Remove client from the list on any error or disconnect
        remove_client(websocket)
        print(f"Enhanced Browser V2 WebSocket client {id(websocket)} disconnected")

@app.websocket("/ws_enhanced_browser_v3")
async def websocket_enhanced_browser_v3_endpoint(websocket: WebSocket):
    """WebSocket endpoint for browser-based audio recording V3 - Live Editing"""
    await websocket.accept()
    
    # Add client to the list
    add_client(websocket)
    print(f"Enhanced Browser V3 WebSocket client {id(websocket)} connected")
    logging.info("Browser audio V3 connection open")
    
    # Import necessary functions
    from .enhanced_logic import (
        transcribe_browser_audio, 
        enhanced_chat_completion,
        enhanced_chat_completion_ollama,
        load_character_prompt,
        sanitize_response,
        analyze_mood,
        characters_folder,
        MAX_CHAR_LENGTH
    )
    from .shared import get_current_character, set_current_character, conversation_history
    
    # Track conversation state and configuration
    is_active = False
    config = {
        'modelProvider': 'ollama',
        'model': 'llama3.2',
        'ttsProvider': 'openai',
        'voice': 'onyx',
        'speed': '1.0',
        'enableGreeting': True,
        'customSystemPrompt': None,
        'customMoodPrompts': {}
    }
    
    try:
        # Notify client they are connected successfully
        await websocket.send_json({"action": "connected", "message": "Browser audio V3 mode ready"})
        
        # Process messages from the client
        while True:
            message = await websocket.receive()

            # Handle disconnects
            if message.get('type') == 'websocket.disconnect':
                code = message.get('code')
                print(f"DEBUG: WebSocket disconnect received (code={code}). Exiting loop.")
                break
            
            if 'text' in message:
                # Handle JSON commands
                try:
                    data = json.loads(message['text'])
                    action = data.get('action')
                    
                    if action == 'start_conversation':
                        # Guard against duplicate starts
                        if is_active:
                            await websocket.send_json({
                                "action": "error",
                                "message": "Conversation already active"
                            })
                            continue
                        
                        # Store configuration
                        character = data.get('character')
                        if character:
                            set_current_character(character)
                        
                        config['modelProvider'] = data.get('modelProvider', 'ollama')
                        config['model'] = data.get('model', 'llama3.2')
                        config['ttsProvider'] = data.get('ttsProvider', 'openai')
                        config['voice'] = data.get('voice', 'onyx')
                        config['speed'] = data.get('speed', '1.0')
                        config['enableGreeting'] = data.get('enableGreeting', True)
                        config['customSystemPrompt'] = data.get('customSystemPrompt')
                        config['customMoodPrompts'] = data.get('customMoodPrompts', {})
                        
                        # Clear old conversation history
                        from .shared import clear_conversation_history
                        clear_conversation_history()
                        
                        is_active = True
                        await websocket.send_json({
                            "action": "conversation_started",
                            "message": f"Started with {config['modelProvider']} + {config['ttsProvider']}"
                        })
                        print(f"Started browser audio V3 conversation with {get_current_character()}")
                        print(f"Config: {config}")
                        print(f"Custom prompts enabled: {config['customSystemPrompt'] is not None}")
                        
                        # Generate greeting if enabled
                        if config['enableGreeting']:
                            try:
                                # Use custom system prompt if provided, otherwise load from file
                                if config['customSystemPrompt']:
                                    base_system_message = config['customSystemPrompt']
                                else:
                                    current_character = get_current_character()
                                    character_prompt_file = os.path.join(characters_folder, current_character, f"{current_character}.txt")
                                    try:
                                        with open(character_prompt_file, 'r', encoding='utf-8') as f:
                                            base_system_message = f.read()
                                    except Exception:
                                        base_system_message = "You are a helpful AI assistant."
                                
                                # Check for custom greeting
                                greeting_override = None
                                if config['customMoodPrompts'] and 'greeting' in config['customMoodPrompts']:
                                    greeting_override = config['customMoodPrompts'].get('greeting')
                                
                                # Create greeting text
                                if greeting_override and greeting_override.strip():
                                    ai_response = greeting_override.strip()
                                else:
                                    # Use configured LLM for greeting
                                    if config['modelProvider'] == 'ollama':
                                        os.environ['OLLAMA_MODEL'] = config['model']
                                        ai_response = await enhanced_chat_completion_ollama(
                                            "Introduce yourself in character with a brief one-sentence greeting and a short question to begin.",
                                            base_system_message,
                                            "",
                                            None
                                        )
                                    else:
                                        if config['modelProvider'] == 'openai':
                                            os.environ['MODEL_PROVIDER'] = 'openai'
                                            os.environ['OPENAI_MODEL'] = config['model']
                                        elif config['modelProvider'] == 'anthropic':
                                            os.environ['MODEL_PROVIDER'] = 'anthropic'
                                            os.environ['ANTHROPIC_MODEL'] = config['model']
                                        elif config['modelProvider'] == 'xai':
                                            os.environ['MODEL_PROVIDER'] = 'xai'
                                            os.environ['XAI_MODEL'] = config['model']
                                        
                                        ai_response = await enhanced_chat_completion(
                                            "Introduce yourself in character with a brief one-sentence greeting and a short question to begin.",
                                            base_system_message,
                                            "",
                                            None
                                        )
                                
                                ai_response = sanitize_response(ai_response)
                                
                                # Add to conversation history
                                conversation_history.append({"role": "assistant", "content": ai_response})
                                
                                # Send text to client
                                await websocket.send_json({
                                    "action": "ai_message",
                                    "message": ai_response
                                })
                                
                                # Generate TTS greeting
                                await websocket.send_json({
                                    "action": "generating_speech",
                                    "message": "Generating greeting..."
                                })
                                
                                # Use configured TTS provider
                                try:
                                    import aiohttp
                                    
                                    if config['ttsProvider'] == 'openai':
                                        openai_api_key = os.getenv("OPENAI_API_KEY")
                                        tts_voice = config['voice']
                                        tts_model = os.getenv("OPENAI_MODEL_TTS", "gpt-4o-mini-tts")
                                        voice_speed = float(config['speed'])
                                        
                                        if not openai_api_key:
                                            raise Exception("OpenAI API key not configured")
                                        
                                        # Call OpenAI TTS API
                                        url = "https://api.openai.com/v1/audio/speech"
                                        headers = {
                                            "Authorization": f"Bearer {openai_api_key}",
                                            "Content-Type": "application/json"
                                        }
                                        payload = {
                                            "model": tts_model,
                                            "input": ai_response,
                                            "voice": tts_voice,
                                            "speed": voice_speed,
                                            "response_format": "wav"
                                        }
                                        
                                        async with aiohttp.ClientSession() as session:
                                            async with session.post(url, headers=headers, json=payload) as response:
                                                if response.status == 200:
                                                    audio_bytes = await response.read()
                                                    await websocket.send_bytes(audio_bytes)
                                                    print(f"Sent greeting audio: {len(audio_bytes)} bytes (OpenAI TTS)")
                                                else:
                                                    error_text = await response.text()
                                                    raise Exception(f"OpenAI TTS error: {response.status} - {error_text}")
                                    
                                    elif config['ttsProvider'] == 'espeak':
                                        # Generate eSpeak TTS for greeting
                                        outputs_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "outputs")
                                        os.makedirs(outputs_dir, exist_ok=True)
                                        temp_audio_path = os.path.join(outputs_dir, "greeting_espeak.wav")
                                        
                                        from .app import espeak_text_to_speech
                                        success = await espeak_text_to_speech(ai_response, temp_audio_path)
                                        
                                        if success and os.path.exists(temp_audio_path):
                                            with open(temp_audio_path, 'rb') as f:
                                                audio_bytes = f.read()
                                            await websocket.send_bytes(audio_bytes)
                                            print(f"Sent greeting audio: {len(audio_bytes)} bytes (eSpeak TTS)")
                                        else:
                                            raise Exception("eSpeak TTS greeting generation failed")

                                    elif config['ttsProvider'] == 'coqui':
                                        # Generate Coqui TTS for greeting
                                        outputs_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "outputs")
                                        os.makedirs(outputs_dir, exist_ok=True)
                                        temp_audio_path = os.path.join(outputs_dir, "greeting_coqui.wav")
                                        
                                        from .app import coqui_text_to_speech
                                        success = await coqui_text_to_speech(ai_response, temp_audio_path)
                                        
                                        if success and os.path.exists(temp_audio_path):
                                            with open(temp_audio_path, 'rb') as f:
                                                audio_bytes = f.read()
                                            await websocket.send_bytes(audio_bytes)
                                            print(f"Sent greeting audio: {len(audio_bytes)} bytes (Coqui TTS)")
                                        else:
                                            raise Exception("Coqui TTS greeting generation failed")

                                    else:
                                        raise Exception(f"TTS provider '{config['ttsProvider']}' not yet implemented")
                                    
                                    await websocket.send_json({
                                        "action": "response_complete",
                                        "message": "Ready for next input"
                                    })
                                    
                                except Exception as e:
                                    print(f"Error generating TTS greeting: {e}")
                                    await websocket.send_json({
                                        "action": "error",
                                        "message": f"TTS Greeting Error: {str(e)}"
                                    })
                                    
                            except Exception as e:
                                print(f"Error generating initial greeting: {e}")
                                import traceback
                                traceback.print_exc()
                        
                    elif action == 'stop_conversation':
                        is_active = False
                        # Clear conversation history
                        from .shared import clear_conversation_history
                        clear_conversation_history()
                        await websocket.send_json({
                            "action": "conversation_stopped",
                            "message": "Conversation stopped"
                        })
                        
                    elif action == 'ping':
                        await websocket.send_json({"action": "pong"})
                        
                except json.JSONDecodeError as e:
                    print(f"Error parsing JSON: {e}")
                    
            elif 'bytes' in message:
                print(f"DEBUG: Binary message received! Size: {len(message['bytes'])} bytes, is_active: {is_active}")
                if not is_active:
                    print(f"DEBUG: Ignoring audio because is_active=False")
                    await websocket.send_json({
                        "action": "conversation_stopped",
                        "message": "Conversation stopped - ignoring audio"
                    })
                    continue
                    
                # Handle binary audio data from browser
                audio_data = message['bytes']
                print(f"Received audio data: {len(audio_data)} bytes")
                
                try:
                    # Notify client we're processing
                    await websocket.send_json({
                        "action": "processing",
                        "message": "Transcribing..."
                    })
                    
                    # Check environment for which transcription to use
                    use_local = os.getenv("FASTER_WHISPER_LOCAL", "true").lower() == "true"
                    
                    # Transcribe the audio
                    transcription = await transcribe_browser_audio(audio_data, use_local_whisper=use_local)
                    
                    if not transcription or transcription.strip() == "":
                        await websocket.send_json({
                            "action": "error",
                            "message": "No speech detected. Please try again."
                        })
                        continue
                    
                    print(f"Transcription: {transcription}")
                    
                    # Send transcription to client
                    await websocket.send_json({
                        "action": "user_message",
                        "message": f"You: {transcription}"
                    })
                    
                    # Add to conversation history
                    conversation_history.append({"role": "user", "content": transcription})
                    
                    # Use custom system prompt if provided
                    if config['customSystemPrompt']:
                        base_system_message = config['customSystemPrompt']
                    else:
                        # Load from file
                        current_character = get_current_character()
                        character_prompt_file = os.path.join(characters_folder, current_character, f"{current_character}.txt")
                        try:
                            with open(character_prompt_file, 'r', encoding='utf-8') as f:
                                base_system_message = f.read()
                        except:
                            base_system_message = "You are a helpful AI assistant."
                    
                    # Analyze mood
                    detected_mood = analyze_mood(transcription)
                    
                    # Get mood prompt (from custom or file)
                    mood_prompt = ""
                    if config['customMoodPrompts'] and detected_mood in config['customMoodPrompts']:
                        mood_prompt = config['customMoodPrompts'].get(detected_mood, "")
                    else:
                        # Try loading from file
                        current_character = get_current_character()
                        character_prompts_path = os.path.join(characters_folder, current_character, 'prompts.json')
                        try:
                            if os.path.exists(character_prompts_path):
                                with open(character_prompts_path, 'r', encoding='utf-8') as f:
                                    mood_prompts = json.load(f)
                                    mood_prompt = mood_prompts.get(detected_mood, "")
                        except:
                            pass
                    
                    # Get AI response using configured provider
                    await websocket.send_json({
                        "action": "ai_thinking",
                        "message": "Thinking..."
                    })
                    
                    # Route to appropriate LLM based on configuration
                    if config['modelProvider'] == 'ollama':
                        # Set environment variable temporarily for this request
                        os.environ['OLLAMA_MODEL'] = config['model']
                        ai_response = await enhanced_chat_completion_ollama(
                            transcription,
                            base_system_message,
                            mood_prompt,
                            conversation_history[:-1] if len(conversation_history) > 1 else None
                        )
                    elif config['modelProvider'] in ['openai', 'anthropic', 'xai']:
                        # Set environment variables temporarily for this request
                        if config['modelProvider'] == 'openai':
                            os.environ['MODEL_PROVIDER'] = 'openai'
                            os.environ['OPENAI_MODEL'] = config['model']
                        elif config['modelProvider'] == 'anthropic':
                            os.environ['MODEL_PROVIDER'] = 'anthropic'
                            os.environ['ANTHROPIC_MODEL'] = config['model']
                        elif config['modelProvider'] == 'xai':
                            os.environ['MODEL_PROVIDER'] = 'xai'
                            os.environ['XAI_MODEL'] = config['model']
                        
                        ai_response = await enhanced_chat_completion(
                            transcription,
                            base_system_message,
                            mood_prompt,
                            conversation_history[:-1] if len(conversation_history) > 1 else None
                        )
                    else:
                        ai_response = "Unsupported model provider"
                    
                    # Clean up response
                    ai_response = sanitize_response(ai_response)
                    
                    # Add to history
                    conversation_history.append({"role": "assistant", "content": ai_response})
                    
                    # Manage history size
                    current_character = get_current_character()
                    if current_character.startswith("story_") or current_character.startswith("game_"):
                        if len(conversation_history) > 100:
                            conversation_history[:] = conversation_history[-100:]
                    else:
                        if len(conversation_history) > 30:
                            conversation_history[:] = conversation_history[-30:]
                    
                    # Send AI response text
                    await websocket.send_json({
                        "action": "ai_message",
                        "message": ai_response
                    })
                    
                    # Generate and send TTS audio based on configured provider
                    await websocket.send_json({
                        "action": "generating_speech",
                        "message": "Generating speech..."
                    })
                    
                    # Generate audio with configured TTS provider
                    try:
                        import aiohttp
                        
                        if config['ttsProvider'] == 'openai':
                            openai_api_key = os.getenv("OPENAI_API_KEY")
                            tts_voice = config['voice']
                            tts_model = os.getenv("OPENAI_MODEL_TTS", "gpt-4o-mini-tts")
                            voice_speed = float(config['speed'])
                            
                            if not openai_api_key:
                                raise Exception("OpenAI API key not configured")
                            
                            # Call OpenAI TTS API
                            url = "https://api.openai.com/v1/audio/speech"
                            headers = {
                                "Authorization": f"Bearer {openai_api_key}",
                                "Content-Type": "application/json"
                            }
                            payload = {
                                "model": tts_model,
                                "input": ai_response,
                                "voice": tts_voice,
                                "speed": voice_speed,
                                "response_format": "wav"
                            }
                            
                            async with aiohttp.ClientSession() as session:
                                async with session.post(url, headers=headers, json=payload) as response:
                                    if response.status == 200:
                                        audio_bytes = await response.read()
                                        await websocket.send_bytes(audio_bytes)
                                        print(f"Sent {len(audio_bytes)} bytes of audio to browser (OpenAI TTS)")
                                    else:
                                        error_text = await response.text()
                                        raise Exception(f"OpenAI TTS error: {response.status} - {error_text}")
                        
                        elif config['ttsProvider'] == 'espeak':
                            # Generate eSpeak TTS
                            outputs_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "outputs")
                            os.makedirs(outputs_dir, exist_ok=True)
                            temp_audio_path = os.path.join(outputs_dir, "browser_espeak.wav")
                            
                            from .app import espeak_text_to_speech
                            success = await espeak_text_to_speech(ai_response, temp_audio_path)
                            
                            if success and os.path.exists(temp_audio_path):
                                with open(temp_audio_path, 'rb') as f:
                                    audio_bytes = f.read()
                                await websocket.send_bytes(audio_bytes)
                                print(f"Sent {len(audio_bytes)} bytes of audio to browser (eSpeak TTS)")
                            else:
                                raise Exception("eSpeak TTS generation failed")

                        elif config['ttsProvider'] == 'coqui':
                            # Generate Coqui TTS
                            outputs_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "outputs")
                            os.makedirs(outputs_dir, exist_ok=True)
                            temp_audio_path = os.path.join(outputs_dir, "browser_coqui.wav")
                            
                            from .app import coqui_text_to_speech
                            success = await coqui_text_to_speech(ai_response, temp_audio_path)
                            
                            if success and os.path.exists(temp_audio_path):
                                with open(temp_audio_path, 'rb') as f:
                                    audio_bytes = f.read()
                                await websocket.send_bytes(audio_bytes)
                                print(f"Sent {len(audio_bytes)} bytes of audio to browser (Coqui TTS)")
                            else:
                                raise Exception("Coqui TTS generation failed")

                        else:
                            raise Exception(f"TTS provider '{config['ttsProvider']}' not yet implemented")
                                    
                    except Exception as e:
                        print(f"Error generating audio: {e}")
                        import traceback
                        traceback.print_exc()
                        await websocket.send_json({
                            "action": "error",
                            "message": f"TTS Error: {str(e)}"
                        })
                    
                    # Notify done
                    await websocket.send_json({
                        "action": "response_complete",
                        "message": "Ready for next input"
                    })
                    
                except Exception as e:
                    print(f"Error processing audio: {e}")
                    import traceback
                    traceback.print_exc()
                    await websocket.send_json({
                        "action": "error",
                        "message": f"Error: {str(e)}"
                    })
                
    except WebSocketDisconnect:
        logging.info("Client disconnected from enhanced browser V3 websocket")
    except Exception as e:
        logging.error(f"Error in enhanced browser V3 websocket: {e}")
        import traceback
        traceback.print_exc()
    finally:
        # Remove client from the list on any error or disconnect
        remove_client(websocket)
        print(f"Enhanced Browser V3 WebSocket client {id(websocket)} disconnected")

# WebRTC OpenAI Realtime route (direct WebRTC implementation)
@app.get("/webrtc_realtime")
async def get_webrtc_realtime(request: Request):
    """
    Serves the WebRTC implementation of OpenAI Realtime API page.
    """
    try:
        # Get characters from characters folder
        characters = []
        if os.path.exists(characters_folder):
            characters = [d for d in os.listdir(characters_folder) 
                        if os.path.isdir(os.path.join(characters_folder, d))]
        
        # Provide a fallback if no characters found
        if not characters:
            characters = ["assistant"]
            logger.warning("No character folders found, using fallback assistant")
        
        # Get realtime model from environment variable or use default
        realtime_model = os.getenv("OPENAI_REALTIME_MODEL", "gpt-4o-realtime-preview-2024-12-17")
            
        return templates.TemplateResponse(
            "webrtc_realtime.html", 
            {
                "request": request,
                "characters": characters,
                "realtime_model": realtime_model,
            }
        )
    except Exception as e:
        logger.error(f"Error rendering WebRTC Realtime page: {e}")
        # Fallback with minimal context
        return templates.TemplateResponse(
            "webrtc_realtime.html", 
            {
                "request": request,
                "characters": ["assistant"],
                "realtime_model": "gpt-4o-realtime-preview-2024-12-17",  # Default fallback
            }
        )

@app.get("/webrtc_realtime_v2")
async def get_webrtc_realtime_v2(request: Request):
    """
    Serves the WebRTC implementation of OpenAI Realtime API page.
    """
    try:
        # Get characters from characters folder
        characters = []
        if os.path.exists(characters_folder):
            characters = [d for d in os.listdir(characters_folder) 
                        if os.path.isdir(os.path.join(characters_folder, d))]
        
        # Provide a fallback if no characters found
        if not characters:
            characters = ["assistant"]
            logger.warning("No character folders found, using fallback assistant")
        
        # Get realtime model from environment variable or use default
        #realtime_model = os.getenv("OPENAI_REALTIME_MODEL", "gpt-4o-realtime-preview-2024-12-17")
        realtime_model = os.getenv("OLLAMA_MODEL", "llama3.2")

        return templates.TemplateResponse(
            "webrtc_realtime_v2.html", 
            {
                "request": request,
                "characters": characters,
                "realtime_model": realtime_model,
            }
        )
    except Exception as e:
        logger.error(f"Error rendering WebRTC Realtime v2 page: {e}")
        # Fallback with minimal context
        return templates.TemplateResponse(
            "webrtc_realtime_v2.html", 
            {
                "request": request,
                "characters": ["assistant"],
                #"realtime_model": "gpt-4o-realtime-preview-2024-12-17",  # Default fallback
                "realtime_model": "llama3.2",
            }
        )

@app.websocket("/ws_ollama_realtime")
async def websocket_ollama_realtime(websocket: WebSocket):
    """
    WebSocket for fully local Ollama-based realtime voice chat
    Uses: Local Whisper + Ollama + Coqui TTS
    Mimics webrtc_realtime UX but with local backend
    """
    await websocket.accept()
    logger.info("Ollama realtime WebSocket client connected")
    
    # Session state
    conversation_history = []
    current_character = "assistant"
    system_prompt = ""
    
    try:
        while True:
            # Receive message from client
            data = await websocket.receive()
            
            # Handle JSON messages (commands)
            if 'text' in data:
                try:
                    message = json.loads(data['text'])
                    action = message.get('action')
                    
                    if action == 'start_session':
                        # Initialize session
                        current_character = message.get('character', 'assistant')
                        logger.info(f"Starting Ollama realtime session with character: {current_character}")
                        
                        # Load character prompt
                        system_prompt = load_character_prompt(current_character)
                        
                        # Send confirmation
                        await websocket.send_json({
                            "type": "session.created",
                            "session": {
                                "character": current_character,
                                "model": os.getenv("OLLAMA_MODEL", "llama3.2")
                            }
                        })
                        
                        # Send ready message
                        await websocket.send_json({
                            "type": "session.updated",
                            "message": "Session started, ready for voice input"
                        })
                        
                        # Generate and send greeting
                        try:
                            # Check for custom greeting in prompts.json
                            greeting_override = None
                            character_prompts_path = os.path.join(characters_folder, current_character, 'prompts.json')
                            try:
                                if os.path.exists(character_prompts_path):
                                    with open(character_prompts_path, 'r', encoding='utf-8') as f:
                                        mood_prompts = json.load(f)
                                        greeting_override = mood_prompts.get('greeting')
                            except Exception:
                                pass
                            
                            # Create greeting text
                            if greeting_override and greeting_override.strip():
                                ai_response = greeting_override.strip()
                            else:
                                # Generate greeting using Ollama
                                from .enhanced_logic import enhanced_chat_completion_ollama
                                ai_response = await enhanced_chat_completion_ollama(
                                    "Introduce yourself in character with a brief one-sentence greeting.",
                                    system_prompt,
                                    "",
                                    []  # Empty history for greeting
                                )
                            
                            # Sanitize response
                            from .app import sanitize_response
                            ai_response = sanitize_response(ai_response)
                            
                            # Add to conversation history
                            conversation_history.append({"role": "assistant", "content": ai_response})
                            
                            # Send greeting text
                            await websocket.send_json({
                                "type": "response.text.done",
                                "text": ai_response
                            })
                            
                            # Generate speech using Coqui TTS
                            import tempfile
                            temp_audio_file = tempfile.mktemp(suffix=".wav")
                            
                            from .app import coqui_text_to_speech
                            success = await coqui_text_to_speech(ai_response, temp_audio_file)
                            
                            if success and os.path.exists(temp_audio_file):
                                with open(temp_audio_file, 'rb') as f:
                                    audio_bytes = f.read()
                                
                                logger.info(f"Sending greeting audio: {len(audio_bytes)} bytes")
                                
                                # Send audio
                                await websocket.send_json({
                                    "type": "response.audio.delta",
                                    "audio_length": len(audio_bytes)
                                })
                                await websocket.send_bytes(audio_bytes)
                                await websocket.send_json({
                                    "type": "response.audio.done"
                                })
                                
                                os.unlink(temp_audio_file)
                            
                            await websocket.send_json({
                                "type": "response.done"
                            })
                            
                        except Exception as e:
                            logger.error(f"Error generating greeting: {e}")
                            import traceback
                            traceback.print_exc()
                        
                    elif action == 'stop_session':
                        logger.info("Stopping Ollama realtime session")
                        conversation_history = []
                        await websocket.send_json({
                            "type": "session.ended"
                        })
                        
                    elif action == 'update_character':
                        current_character = message.get('character', current_character)
                        system_prompt = load_character_prompt(current_character)
                        logger.info(f"Updated character to: {current_character}")
                        
                except json.JSONDecodeError:
                    logger.error("Invalid JSON received")
                    
            # Handle binary data (audio)
            elif 'bytes' in data:
                audio_data = data['bytes']
                logger.info(f"Received {len(audio_data)} bytes of audio")
                
                try:
                    # Send acknowledgment
                    await websocket.send_json({
                        "type": "input_audio_buffer.committed",
                        "message": "Processing audio..."
                    })
                    
                    # Transcribe using local Faster Whisper
                    from .enhanced_logic import transcribe_browser_audio
                    logger.info("Transcribing with local Whisper...")
                    transcription = await transcribe_browser_audio(audio_data, use_local_whisper=True)
                    
                    if not transcription or transcription.strip() == "":
                        logger.warning("Empty transcription received")
                        await websocket.send_json({
                            "type": "error",
                            "error": {"message": "No speech detected"}
                        })
                        continue
                    
                    logger.info(f"Transcription: {transcription}")
                    
                    # Send transcription to client
                    await websocket.send_json({
                        "type": "conversation.item.input_audio_transcription.completed",
                        "transcript": transcription
                    })
                    
                    # Add to conversation history
                    conversation_history.append({"role": "user", "content": transcription})
                    
                    # Get response from Ollama
                    from .enhanced_logic import enhanced_chat_completion_ollama
                    logger.info("Getting response from Ollama...")
                    ai_response = await enhanced_chat_completion_ollama(
                        transcription,
                        system_prompt,
                        "",  # mood_prompt
                        conversation_history
                    )
                    
                    if not ai_response:
                        raise Exception("Empty response from Ollama")
                    
                    logger.info(f"AI Response: {ai_response[:100]}...")
                    
                    # Add AI response to history
                    conversation_history.append({"role": "assistant", "content": ai_response})
                    
                    # Send AI text response
                    await websocket.send_json({
                        "type": "response.text.done",
                        "text": ai_response
                    })
                    
                    # Generate speech using Coqui TTS
                    import tempfile
                    temp_audio_file = tempfile.mktemp(suffix=".wav")
                    
                    logger.info("Generating speech with Coqui TTS...")
                    
                    # Use the coqui_text_to_speech function from app.py
                    from .app import coqui_text_to_speech
                    
                    success = await coqui_text_to_speech(ai_response, temp_audio_file)
                    
                    if success and os.path.exists(temp_audio_file):
                        # Read audio file and send to client
                        with open(temp_audio_file, 'rb') as f:
                            audio_bytes = f.read()
                        
                        logger.info(f"Sending {len(audio_bytes)} bytes of audio to client")
                        
                        # Send audio data notification
                        await websocket.send_json({
                            "type": "response.audio.delta",
                            "audio_length": len(audio_bytes)
                        })
                        
                        # Send actual audio bytes
                        await websocket.send_bytes(audio_bytes)
                        
                        # Send completion message
                        await websocket.send_json({
                            "type": "response.audio.done",
                            "message": "Audio playback complete"
                        })
                        
                        # Clean up temp file
                        try:
                            os.unlink(temp_audio_file)
                        except:
                            pass
                    else:
                        logger.error("Coqui TTS generation failed")
                        await websocket.send_json({
                            "type": "error",
                            "error": {"message": "TTS generation failed"}
                        })
                    
                    # Send final completion
                    await websocket.send_json({
                        "type": "response.done"
                    })
                    
                except Exception as e:
                    logger.error(f"Error processing audio: {e}")
                    import traceback
                    traceback.print_exc()
                    await websocket.send_json({
                        "type": "error",
                        "error": {"message": str(e)}
                    })
                    
    except WebSocketDisconnect:
        logger.info("Ollama realtime WebSocket client disconnected")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        import traceback
        traceback.print_exc()

@app.get("/api/character/{character_name}")
async def get_character_prompt(character_name: str):
    """
    Get the prompt for a specific character
    """
    try:
        prompt = load_character_prompt(character_name)
        return {"prompt": prompt}
    except Exception as e:
        logger.error(f"Error loading character prompt: {e}")
        return {"error": str(e)}

@app.get("/get_character_history")
async def get_character_history():
    """Get conversation history for currently selected character."""
    try:
        # Import with alias to avoid potential shadowing issues
        from .shared import get_current_character as get_character
        
        current_character = get_character()
        
        # Check if this is a story or game character
        is_story_character = current_character.startswith("story_") or current_character.startswith("game_")
        print(f"Getting history for {current_character} ({is_story_character=})")
        
        if is_story_character:
            # Get from character-specific history file
            character_dir = os.path.join(characters_folder, current_character)
            history_file = os.path.join(character_dir, "conversation_history.txt")
            
            if os.path.exists(history_file) and os.path.getsize(history_file) > 0:
                with open(history_file, 'r', encoding='utf-8') as f:
                    history_text = f.read()
                return {"status": "success", "history": history_text, "character": current_character}
            else:
                return {"status": "empty", "history": "", "character": current_character}
        else:
            # For non-story characters, return empty history
            return {"status": "not_story_character", "history": "", "character": current_character}
    except Exception as e:
        print(f"Error getting character history: {e}")
        return {"status": "error", "message": str(e)}

@app.get("/kokoro_voices")
async def get_kokoro_voices():
    try:
        # Get the base URL from environment or use default
        kokoro_base_url = os.getenv("KOKORO_BASE_URL", "http://localhost:8880/v1")
        
        # Get authentication credentials
        kokoro_username = os.getenv("KOKORO_USERNAME", "")
        kokoro_password = os.getenv("KOKORO_PASSWORD", "")
        
        # Prepare auth headers if credentials are provided
        headers = {}
        if kokoro_username and kokoro_password:
            import base64
            auth_str = f"{kokoro_username}:{kokoro_password}"
            auth_bytes = auth_str.encode('ascii')
            base64_auth = base64.b64encode(auth_bytes).decode('ascii')
            headers["Authorization"] = f"Basic {base64_auth}"
        
        try:
            # Use the correct API endpoint for voices
            voices_url = f"{kokoro_base_url}/audio/voices"
            
            # Make HTTP request directly with SSL verification disabled
            connector = aiohttp.TCPConnector(ssl=False)
            async with aiohttp.ClientSession(connector=connector) as session:
                try:
                    async with session.get(voices_url, headers=headers, timeout=3) as response:
                        if response.status == 200:
                            data = await response.json()
                            # Process the voices from the response
                            voices = []
                            
                            # Language/accent codes mapping
                            language_codes = {
                                'a': 'American English',
                                'b': 'British English',
                                'e': 'European Spanish',
                                'f': 'French',
                                'g': 'German',
                                'h': 'Hindi',
                                'i': 'Italian',
                                'j': 'Japanese',
                                'k': 'Korean',
                                'p': 'Polish',
                                'r': 'Russian',
                                's': 'Spanish',
                                'z': 'Chinese'
                            }
                            
                            # Get all voice IDs
                            voice_ids = data.get("voices", [])
                            
                            # Group voices by language/accent
                            english_voices = []  # American and British English
                            other_voices_by_language = {}  # Organize other voices by language code
                            unknown_voices = []
                            
                            for voice_id in voice_ids:
                                parts = voice_id.split('_')
                                if len(parts) >= 2:
                                    lang_code = parts[0]
                                    # First character is language code
                                    accent_code = lang_code[:1]
                                    
                                    # Prioritize English voices (American and British)
                                    if accent_code in ['a', 'b']:
                                        english_voices.append(voice_id)
                                    else:
                                        # Group other voices by language
                                        if accent_code not in other_voices_by_language:
                                            other_voices_by_language[accent_code] = []
                                        other_voices_by_language[accent_code].append(voice_id)
                                else:
                                    unknown_voices.append(voice_id)
                            
                            # Sort voices within each group
                            english_voices.sort()
                            for lang in other_voices_by_language:
                                other_voices_by_language[lang].sort()
                            unknown_voices.sort()
                            
                            # Create final sorted list: English first, then other languages alphabetically
                            sorted_voice_ids = english_voices
                            
                            # Process English voices
                            for voice_id in english_voices:
                                parts = voice_id.split('_')
                                if len(parts) >= 2:
                                    lang_code = parts[0]
                                    name = parts[1].capitalize()
                                    
                                    accent_code = lang_code[:1]
                                    gender_code = lang_code[1:2]
                                    
                                    gender = "Female" if gender_code == "f" else "Male"
                                    accent_label = f" - {language_codes.get(accent_code, 'Unknown')}"
                                    
                                    voices.append({
                                        "id": voice_id,
                                        "name": f"{name} ({gender}){accent_label}"
                                    })
                            
                            # Add other language groups with separators
                            for lang in sorted(other_voices_by_language.keys()):
                                # Add a language group header if we have voices for this language
                                if other_voices_by_language[lang]:
                                    language_name = language_codes.get(lang, "Unknown Language")
                                    
                                    # Add a separator for this language group
                                    voices.append({
                                        "id": f"separator_{lang}",
                                        "name": f"--- {language_name} Voices ---"
                                    })
                                    
                                    # Add the voices for this language
                                    for voice_id in other_voices_by_language[lang]:
                                        parts = voice_id.split('_')
                                        if len(parts) >= 2:
                                            name = parts[1].capitalize()
                                            gender_code = parts[0][1:2]
                                            gender = "Female" if gender_code == "f" else "Male"
                                            
                                            voices.append({
                                                "id": voice_id,
                                                "name": f"{name} ({gender})"
                                            })
                            
                            # Add unknown voices at the end if any
                            if unknown_voices:
                                voices.append({
                                    "id": "separator_unknown",
                                    "name": "--- Other Voices ---"
                                })
                                
                                for voice_id in unknown_voices:
                                    voices.append({
                                        "id": voice_id,
                                        "name": voice_id
                                    })
                            
                            return {"voices": voices}
                        else:
                            # Log the error and return empty voices
                            error_text = await response.text()
                            logger.error(f"Error fetching Kokoro voices: HTTP {response.status} - {error_text}")
                            return {"voices": [], "error": f"HTTP Error: {response.status}"}
                except aiohttp.ClientConnectorError as e:
                    # Handle connection errors specifically (server not available)
                    logger.info(f"Kokoro server not available at {kokoro_base_url} - This is normal if you don't have Kokoro running")
                    return {"voices": [], "error": "Kokoro server not available"}
                except asyncio.TimeoutError:
                    # Handle timeout errors
                    # logger.info(f"Timeout connecting to Kokoro server at {kokoro_base_url}")
                    return {"voices": [], "error": "Connection timeout"}
            
        except Exception as e:
            # Log the error and return empty voices with error message
            logger.error(f"Error fetching Kokoro voices: {str(e)}")
            return {"voices": [], "error": str(e)}
            
    except Exception as e:
        logger.error(f"Critical error in get_kokoro_voices: {str(e)}")
        return {"voices": [], "error": str(e)}

def signal_handler(sig, frame):
    print('\nShutting down gracefully... Press Ctrl+C again to force exit')
    
    try:
        # Stop any active enhanced conversation
        try:
            # For async shutdown in sync context, create a new event loop
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            # First stop any active conversations
            from .enhanced_logic import enhanced_conversation_active, stop_enhanced_conversation
            if enhanced_conversation_active:
                print("Stopping active enhanced conversation...")
                loop.run_until_complete(stop_enhanced_conversation())
                
            # Then close all WebSocket connections
            for client in list(clients):  # Create a copy of the clients set to avoid modification during iteration
                try:
                    if hasattr(client, 'close'):
                        # Use the same loop for consistency
                        loop.run_until_complete(client.close())
                except Exception as e:
                    print(f"Error closing client: {e}")
                    
            loop.close()
        except Exception as e:
            print(f"Error in graceful shutdown: {e}")
        
        print("Shutdown procedures completed. Exiting...")
        import os
        os._exit(0)  # Force exit as sys.exit() might not work if asyncio is running
        
    except Exception as e:
        print(f"Error during shutdown: {e}")
        import os
        os._exit(1)  # Error exit code

if __name__ == "__main__":
    # Register signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    try:
        print("Starting server. Press Ctrl+C to exit.")
        uvicorn.run(app, host="0.0.0.0", port=8000)
    except KeyboardInterrupt:
        print("\nServer stopped by keyboard interrupt.")
    finally:
        print("Shutdown complete.")