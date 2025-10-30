/**
 * Ollama Realtime Voice Chat - WebSocket Implementation
 * Mimics WebRTC UX but uses WebSocket + Local Whisper + Ollama + Coqui XTTS
 */

document.addEventListener("DOMContentLoaded", function() {
    // DOM elements
    const startButton = document.getElementById('startBtn');
    const stopButton = document.getElementById('stopBtn');
    const clearButton = document.getElementById('clearBtn');
    const testMicButton = document.getElementById('testMicBtn');
    const micButton = document.getElementById('micBtn');
    const micStatus = document.getElementById('micStatus');
    const transcript = document.getElementById('transcript');
    const sessionStatus = document.getElementById('session-status');
    const characterSelect = document.getElementById('character-select');
    const voiceSelect = document.getElementById('voice-select');
    const userVoiceVisualization = document.getElementById('userVoiceVisualization');
    const aiVoiceVisualization = document.getElementById('aiVoiceVisualization');
    const waitingIndicator = document.getElementById('waitingIndicator');
    
    // Global state
    let websocket = null;
    let mediaRecorder = null;
    let micStream = null;
    let isSessionActive = false;
    let isMicrophoneActive = false;
    let audioContext = null;
    let audioPlayer = new Audio();
    let isProcessing = false;
    
    // Setup event listeners
    startButton.addEventListener('click', startSession);
    stopButton.addEventListener('click', stopSession);
    micButton.addEventListener('click', toggleMicrophone);
    clearButton.addEventListener('click', clearTranscript);
    if (testMicButton) {
        testMicButton.addEventListener('click', testMicrophone);
    }
    
    // Info toggle
    const infoToggleBtn = document.getElementById('infoToggleBtn');
    const infoBox = document.getElementById('infoBox');
    if (infoToggleBtn && infoBox) {
        infoToggleBtn.addEventListener('click', () => {
            if (infoBox.style.display === 'none') {
                infoBox.style.display = 'block';
                infoToggleBtn.innerHTML = '<i class="fas fa-info-circle"></i> Hide Usage Guide';
            } else {
                infoBox.style.display = 'none';
                infoToggleBtn.innerHTML = '<i class="fas fa-info-circle"></i> Show Usage Guide';
            }
        });
    }
    
    // Start session
    async function startSession() {
        try {
            console.log("Starting Ollama realtime session...");
            sessionStatus.textContent = "Connecting...";
            sessionStatus.classList.remove("badge-secondary");
            sessionStatus.classList.add("badge-warning");
            startButton.disabled = true;
            
            // Connect WebSocket
            const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
            websocket = new WebSocket(`${protocol}//${window.location.host}/ws_ollama_realtime`);
            
            websocket.onopen = async () => {
                console.log("WebSocket connected");
                
                // Send start session message
                websocket.send(JSON.stringify({
                    action: 'start_session',
                    character: characterSelect.value
                }));
            };
            
            websocket.onmessage = handleWebSocketMessage;
            
            websocket.onerror = (error) => {
                console.error("WebSocket error:", error);
                addTranscriptMessage("Connection error", "error");
                stopSession();
            };
            
            websocket.onclose = () => {
                console.log("WebSocket closed");
                if (isSessionActive) {
                    addTranscriptMessage("Connection closed", "system");
                    stopSession();
                }
            };
            
        } catch (error) {
            console.error("Error starting session:", error);
            addTranscriptMessage(`Error: ${error.message}`, "error");
            stopSession();
        }
    }
    
    // Handle WebSocket messages
    async function handleWebSocketMessage(event) {
        if (event.data instanceof Blob) {
            // Audio data received
            console.log("Received audio blob:", event.data.size, "bytes");
            
            // Play audio
            const audioUrl = URL.createObjectURL(event.data);
            audioPlayer.src = audioUrl;
            
            // Show AI voice visualization
            aiVoiceVisualization.classList.remove('hidden');
            animateVoiceBars('aiVoiceVisualization');
            
            audioPlayer.play().catch(e => {
                console.error("Error playing audio:", e);
            });
            
            audioPlayer.onended = () => {
                aiVoiceVisualization.classList.add('hidden');
                URL.revokeObjectURL(audioUrl);
                isProcessing = false;
                
                // Ready for next input
                if (isSessionActive) {
                    micStatus.textContent = "Click to speak";
                    updateHeaderMicIcon(false);
                }
            };
            
            return;
        }
        
        // JSON message
        try {
            const data = JSON.parse(event.data);
            console.log("Received message:", data.type);
            
            if (data.type === "session.created") {
                // Initial session creation - setup microphone
                if (!micStream) {
                    await setupMicrophone();
                }
                
            } else if (data.type === "session.updated") {
                // Session fully ready
                isSessionActive = true;
                sessionStatus.textContent = "Active";
                sessionStatus.classList.remove("badge-warning");
                sessionStatus.classList.add("badge-success");
                stopButton.disabled = false;
                micButton.disabled = false;
                
                addTranscriptMessage(`Session started with ${characterSelect.value}`, "system");
                addTranscriptMessage("Click microphone button to start recording", "system");
                
            } else if (data.type === "input_audio_buffer.committed") {
                addTranscriptMessage("Processing...", "system");
                isProcessing = true;
                userVoiceVisualization.classList.add('hidden');
                
            } else if (data.type === "conversation.item.input_audio_transcription.completed") {
                // Show user's transcribed speech
                addTranscriptMessage(`You: ${data.transcript}`, "user");
                
            } else if (data.type === "response.text.done") {
                // Show AI text response
                addTranscriptMessage(`AI: ${data.text}`, "ai");
                
            } else if (data.type === "response.audio.delta") {
                console.log("Receiving audio...");
                
            } else if (data.type === "response.done") {
                console.log("Response complete");
                
            } else if (data.type === "error") {
                console.error("Server error:", data.error);
                addTranscriptMessage(`Error: ${data.error.message}`, "error");
                isProcessing = false;
            }
            
        } catch (error) {
            console.error("Error parsing message:", error);
        }
    }
    
    // Setup microphone
    async function setupMicrophone() {
        try {
            console.log("Requesting microphone access...");
            micStream = await navigator.mediaDevices.getUserMedia({
                audio: {
                    channelCount: 1,
                    sampleRate: 16000,
                    echoCancellation: true,
                    noiseSuppression: true,
                    autoGainControl: true
                }
            });
            
            console.log("Microphone access granted");
            
            // Setup audio context for visualization
            audioContext = new (window.AudioContext || window.webkitAudioContext)();
            const analyser = audioContext.createAnalyser();
            const microphone = audioContext.createMediaStreamSource(micStream);
            const scriptProcessor = audioContext.createScriptProcessor(2048, 1, 1);
            
            analyser.smoothingTimeConstant = 0.8;
            analyser.fftSize = 1024;
            
            microphone.connect(analyser);
            analyser.connect(scriptProcessor);
            scriptProcessor.connect(audioContext.destination);
            
            scriptProcessor.onaudioprocess = function() {
                if (!isMicrophoneActive) return;
                
                const array = new Uint8Array(analyser.frequencyBinCount);
                analyser.getByteFrequencyData(array);
                
                let values = 0;
                for (let i = 0; i < array.length; i++) {
                    values += array[i];
                }
                const average = values / array.length;
                
                if (average > 10) {
                    updateHeaderMicIcon(true);
                } else {
                    updateHeaderMicIcon(false);
                }
            };
            
            // Setup MediaRecorder for sending audio
            mediaRecorder = new MediaRecorder(micStream, {
                mimeType: 'audio/webm;codecs=opus'
            });
            
            let audioChunks = [];
            
            mediaRecorder.ondataavailable = (event) => {
                if (event.data.size > 0) {
                    audioChunks.push(event.data);
                }
            };
            
            mediaRecorder.onstop = async () => {
                // Only send if we have audio, websocket is open, and session is active
                if (audioChunks.length > 0 && websocket && websocket.readyState === WebSocket.OPEN && isSessionActive) {
                    const audioBlob = new Blob(audioChunks, { type: 'audio/webm' });
                    console.log("Sending audio to server:", audioBlob.size, "bytes");
                    
                    // Send audio as binary
                    websocket.send(await audioBlob.arrayBuffer());
                }
                // Always clear chunks
                audioChunks = [];
            };
            
            return true;
        } catch (error) {
            console.error("Error accessing microphone:", error);
            addTranscriptMessage(`Microphone error: ${error.message}`, "error");
            return false;
        }
    }
    
    // Toggle microphone
    function toggleMicrophone() {
        if (!isSessionActive) {
            addTranscriptMessage("Please start a session first", "system");
            return;
        }
        
        if (!mediaRecorder) {
            addTranscriptMessage("Microphone not initialized", "error");
            return;
        }
        
        if (isMicrophoneActive) {
            // Stop recording and send
            isMicrophoneActive = false;
            if (mediaRecorder.state === 'recording') {
                mediaRecorder.stop();
            }
            micButton.classList.remove('listening');
            micStatus.textContent = "Processing...";
            updateHeaderMicIcon(false);
            userVoiceVisualization.classList.add('hidden');
            
        } else {
            // Start recording
            if (isProcessing) {
                addTranscriptMessage("Please wait for AI response to complete", "system");
                return;
            }
            
            isMicrophoneActive = true;
            mediaRecorder.start();
            micButton.classList.add('listening');
            micStatus.textContent = "🎤 Recording... Click again to send";
            updateHeaderMicIcon(true);
            userVoiceVisualization.classList.remove('hidden');
            animateVoiceBars('userVoiceVisualization');
        }
    }
    
    // Stop session
    function stopSession() {
        console.log("Stopping session...");
        
        // Disable session first to prevent audio sending
        isSessionActive = false;
        isMicrophoneActive = false;
        isProcessing = false;
        
        // Stop recording if active (won't send due to isSessionActive = false)
        if (mediaRecorder && mediaRecorder.state === 'recording') {
            mediaRecorder.stop();
        }
        
        // Stop microphone stream
        if (micStream) {
            micStream.getTracks().forEach(track => track.stop());
            micStream = null;
        }
        
        // Close websocket
        if (websocket) {
            try {
                if (websocket.readyState === WebSocket.OPEN) {
                    websocket.send(JSON.stringify({ action: 'stop_session' }));
                }
                websocket.close();
            } catch (e) {
                console.log("Error closing websocket:", e);
            }
            websocket = null;
        }
        
        // Reset UI
        sessionStatus.textContent = "Inactive";
        sessionStatus.classList.remove("badge-success", "badge-warning");
        sessionStatus.classList.add("badge-secondary");
        
        startButton.disabled = false;
        stopButton.disabled = true;
        micButton.disabled = true;
        micButton.classList.remove('listening');
        micStatus.textContent = "Click to speak";
        
        updateHeaderMicIcon(false);
        userVoiceVisualization.classList.add('hidden');
        aiVoiceVisualization.classList.add('hidden');
        
        addTranscriptMessage("Session ended", "system");
    }
    
    // Clear transcript
    function clearTranscript() {
        transcript.innerHTML = '';
    }
    
    // Add message to transcript
    function addTranscriptMessage(text, type = "system") {
        const messageDiv = document.createElement('div');
        messageDiv.classList.add(type + '-message');
        messageDiv.textContent = text;
        transcript.appendChild(messageDiv);
        transcript.scrollTop = transcript.scrollHeight;
    }
    
    // Update header mic icon
    function updateHeaderMicIcon(isActive) {
        const micIcon = document.getElementById('mic-icon');
        if (!micIcon) return;
        
        if (!isSessionActive) {
            micIcon.className = 'mic-off';
        } else if (isActive) {
            micIcon.className = 'mic-on pulse-animation';
        } else {
            micIcon.className = 'mic-waiting';
        }
    }
    
    // Animate voice bars
    function animateVoiceBars(elementId) {
        const voiceVisualization = document.getElementById(elementId);
        if (!voiceVisualization) return;
        
        if (voiceVisualization.querySelectorAll('.voice-bar').length === 0) {
            for (let i = 0; i < 8; i++) {
                const bar = document.createElement('div');
                bar.classList.add('voice-bar');
                voiceVisualization.appendChild(bar);
            }
        }
        
        const bars = voiceVisualization.querySelectorAll('.voice-bar');
        const interval = setInterval(() => {
            if (voiceVisualization.classList.contains('hidden')) {
                clearInterval(interval);
                return;
            }
            
            bars.forEach(bar => {
                const height = Math.random() * 50 + 10;
                bar.style.height = height + 'px';
                bar.classList.add('active-bar');
            });
        }, 100);
    }
    
    // Test microphone
    async function testMicrophone() {
        try {
            const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
            addTranscriptMessage("Microphone test successful!", "system");
            stream.getTracks().forEach(track => track.stop());
        } catch (error) {
            addTranscriptMessage(`Microphone test failed: ${error.message}`, "error");
        }
    }
});