// app.js
const chatForm = document.getElementById('chat-form');
const chatInput = document.getElementById('chat-input');
const chatWindow = document.getElementById('chat-window');
const eventsList = document.getElementById('events-list');
const filterBtns = document.querySelectorAll('.filter-btn');

const wsStatusDot = document.getElementById('ws-status-dot');
const wsStatusText = document.getElementById('ws-status-text');

const sessionId = `ctx-${Math.random().toString(36).substring(2, 11)}`;

let ws;
let currentFilter = 'all';

const navChat = document.getElementById('nav-chat');
const navArch = document.getElementById('nav-arch');
const appUiContainer = document.getElementById('app-ui-container');
const archContainer = document.getElementById('architecture-container');

navChat.addEventListener('click', (e) => {
    e.preventDefault();
    navChat.classList.add('active');
    navArch.classList.remove('active');
    appUiContainer.style.display = 'flex';
    archContainer.style.display = 'none';
});

navArch.addEventListener('click', (e) => {
    e.preventDefault();
    navArch.classList.add('active');
    navChat.classList.remove('active');
    appUiContainer.style.display = 'none';
    archContainer.style.display = 'block';
});

function connectWebSocket() {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    ws = new WebSocket(`${protocol}//${window.location.host}/ws/events`);

    ws.onopen = () => {
        wsStatusDot.classList.add('connected');
        wsStatusText.textContent = 'Connected';
    };

    ws.onclose = () => {
        wsStatusDot.classList.remove('connected');
        wsStatusText.textContent = 'Disconnected (Retrying...)';
        setTimeout(connectWebSocket, 3000);
    };

    ws.onmessage = (event) => {
        try {
            const data = JSON.parse(event.data);
            appendEvent(data);
        } catch (e) {
            console.error('Failed to parse event data:', e);
        }
    };
}

chatForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    const message = chatInput.value.trim();
    if (!message) return;

    appendMessage(message, 'user');
    chatInput.value = '';
    chatInput.disabled = true;

    try {
        const payload = {
            jsonrpc: "2.0",
            id: `msg-${Date.now()}`,
            method: "message/send",
            params: {
                message: {
                    messageId: `id-${Date.now()}`,
                    contextId: sessionId,
                    role: "user",
                    parts: [{ text: message }]
                }
            }
        };

        appendEvent({
            source: "Browser Client (A2A)",
            type: "JSON-RPC Request",
            payload: payload
        });

        const response = await fetch('/api/a2a/', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        
        const data = await response.json();
        
        appendEvent({
            source: "A2A Server",
            type: "JSON-RPC Response",
            payload: data
        });

        let messageText = null;
        if (data.error) {
            appendMessage(`A2A Error: ${data.error.message}`, 'system');
        } else {
            try {
                const payload = data.result ? data.result : data;
                if (payload.status?.message?.parts?.[0]?.text) {
                    messageText = payload.status.message.parts[0].text;
                } else if (payload.parts?.[0]?.text) {
                    messageText = payload.parts[0].text;
                }
            } catch (err) {
                messageText = "Task completed."; 
            }
            if (messageText) {
                let agentAvatar = 'ADK';
                const match = messageText.match(/^\[(.*?)\]\s*(.*)/s);
                
                if (match) {
                    const fullName = match[1];
                    messageText = match[2];
                    
                    agentAvatar = fullName.substring(0, 4).toUpperCase();
                }
                
                appendMessage(messageText, 'agent', agentAvatar);
            }
        }
    } catch (err) {
        appendMessage(`Error: ${err.message}`, 'system');
    } finally {
        chatInput.disabled = false;
        chatInput.focus();
    }
});

filterBtns.forEach(btn => {
    btn.addEventListener('click', () => {
        filterBtns.forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        currentFilter = btn.dataset.filter;
        const cards = document.querySelectorAll('.event-card');
        cards.forEach(card => {
            if (currentFilter === 'all' || card.classList.contains(currentFilter)) {
                card.style.display = 'block';
            } else {
                card.style.display = 'none';
            }
        });
    });
});

function appendMessage(text, role, avatarText = null) {
    const msgDiv = document.createElement('div');
    msgDiv.className = `message ${role}-msg`;
    
    const avatar = document.createElement('div');
    avatar.className = 'msg-avatar';
    if (role === 'user') avatar.textContent = 'USR';
    else if (role === 'agent') avatar.textContent = avatarText || 'ADK';
    else avatar.textContent = 'SYS';
    
    const content = document.createElement('div');
    content.className = 'msg-content';
    
    content.innerHTML = marked.parse(text);
    
    if (window.renderMathInElement) {
        renderMathInElement(content, {
            delimiters: [
                {left: '$$', right: '$$', display: true},
                {left: '\\[', right: '\\]', display: true},
                {left: '$', right: '$', display: false},
                {left: '\\(', right: '\\)', display: false}
            ],
            throwOnError: false
        });
    }

    msgDiv.appendChild(avatar);
    msgDiv.appendChild(content);
    chatWindow.appendChild(msgDiv);
    chatWindow.scrollTop = chatWindow.scrollHeight;
}

function appendEvent(eventData) {
    const placeholder = eventsList.querySelector('.event-placeholder');
    if (placeholder) placeholder.remove();
    const isMCP = eventData.source.includes('MCP') || eventData.source.includes('FastMCP');
    const isA2A = eventData.source.includes('A2A');
    const categoryClass = isMCP ? 'mcp' : (isA2A ? 'a2a' : 'mcp');
    const badgeText = isMCP ? 'MCP' : 'A2A';
    const card = document.createElement('div');
    card.className = `event-card ${categoryClass}`;
    if (currentFilter !== 'all' && currentFilter !== categoryClass) card.style.display = 'none';
    const header = document.createElement('div');
    header.className = 'event-card-header';
    header.innerHTML = `
        <span class="event-title">${eventData.source} :: [${eventData.type}]</span>
        <span class="event-badge">${badgeText}</span>
    `;
    const bodyContainer = document.createElement('div');
    bodyContainer.className = 'event-body';
    const pre = document.createElement('pre');
    pre.innerHTML = syntaxHighlight(JSON.stringify(eventData.payload, null, 2));
    bodyContainer.appendChild(pre);
    card.appendChild(header);
    card.appendChild(bodyContainer);
    eventsList.appendChild(card);
    eventsList.scrollTop = eventsList.scrollHeight;
}

function syntaxHighlight(json) {
    json = json.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    return json.replace(/("(\\u[a-zA-Z0-9]{4}|\\[^u]|[^\\"])*"(\s*:)?|\b(true|false|null)\b|-?\d+(?:\.\d*)?(?:[eE][+\-]?\d+)?)/g, function (match) {
        let cls = 'json-number';
        if (/^"/.test(match)) {
            if (/:$/.test(match)) cls = 'json-key';
            else cls = 'json-string';
        } else if (/true|false/.test(match)) cls = 'json-boolean';
        else if (/null/.test(match)) cls = 'json-null';
        return '<span class="' + cls + '">' + match + '</span>';
    });
}

connectWebSocket();