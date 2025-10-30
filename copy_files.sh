sudo docker cp /home/ubuntu/newcode/app/main.py  voice-chat-ai:/app/app/main.py
sudo docker cp /home/ubuntu/newcode/app/app.py  voice-chat-ai:/app/app/app.py
sudo docker cp /home/ubuntu/newcode/app/shared.py  voice-chat-ai:/app/app/shared.py
sudo docker cp /home/ubuntu/newcode/app/transcription.py  voice-chat-ai:/app/app/transcription.py
sudo docker cp /home/ubuntu/newcode/app/enhanced_logic.py  voice-chat-ai:/app/app/enhanced_logic.py

sudo docker cp /home/ubuntu/newcode/cli.py  voice-chat-ai:/app/cli.py
sudo docker cp /home/ubuntu/newcode/requirements.txt  voice-chat-ai:/app/requirements.txt
sudo docker cp /home/ubuntu/newcode/requirements_cpu.txt  voice-chat-ai:/app/requirements_cpu.txt


sudo docker cp /home/ubuntu/newcode/app/templates/enhanced_browser.html  voice-chat-ai:/app/app/templates/enhanced_browser.html
sudo docker cp /home/ubuntu/newcode/app/templates/enhanced_browser_v2.html  voice-chat-ai:/app/app/templates/enhanced_browser_v2.html
sudo docker cp /home/ubuntu/newcode/app/templates/enhanced_browser_v3.html  voice-chat-ai:/app/app/templates/enhanced_browser_v3.html
sudo docker cp /home/ubuntu/newcode/app/templates/webrtc_realtime_v2.html  voice-chat-ai:/app/app/templates/webrtc_realtime_v2.html
sudo docker cp /home/ubuntu/newcode/app/templates/index.html  voice-chat-ai:/app/app/templates/index.html
sudo docker cp /home/ubuntu/newcode/app/templates/webrtc_realtime.html  voice-chat-ai:/app/app/templates/webrtc_realtime.html

sudo docker cp /home/ubuntu/newcode/app/static/js/scripts.js  voice-chat-ai:/app/app/static/js/scripts.js
sudo docker cp /home/ubuntu/newcode/app/static/js/enhanced.js  voice-chat-ai:/app/app/static/js/enhanced.js
sudo docker cp /home/ubuntu/newcode/app/static/js/webrtc_realtime_v2.js  voice-chat-ai:/app/app/static/js/webrtc_realtime_v2.js
