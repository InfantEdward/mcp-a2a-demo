const chatForm = document.getElementById('chat-form');
const chatInput = document.getElementById('chat-input');
const chatWindow = document.getElementById('chat-window');
const eventsList = document.getElementById('events-list');
const filterBtns = document.querySelectorAll('.filter-btn');

const wsStatusDot = document.getElementById('ws-status-dot');
const wsStatusText = document.getElementById('ws-status-text');

const navChat = document.getElementById('nav-chat');
const navArch = document.getElementById('nav-arch');
const appUiContainer = document.getElementById('app-ui-container');
const archContainer = document.getElementById('architecture-container');

const routingRationale = document.getElementById('routing-rationale');
const traceList = document.getElementById('trace-list');
const timelineList = document.getElementById('timeline-list');
const networkGraph = document.getElementById('network-graph');
const nodeInspector = document.getElementById('node-inspector');
const tokenStats = document.getElementById('token-stats');
const newsInboxCard = document.getElementById('news-inbox-card');
const newsInboxStatus = document.getElementById('news-inbox-status');
const newsRequestBody = document.getElementById('news-request-body');
const newsResponseForm = document.getElementById('news-response-form');
const newsResponseInput = document.getElementById('news-response-input');

const metricTotal = document.getElementById('metric-total');
const metricA2A = document.getElementById('metric-a2a');
const metricMCP = document.getElementById('metric-mcp');
const metricLatency = document.getElementById('metric-latency');
const archRouting = document.getElementById('arch-routing');
const archSequence = document.getElementById('arch-sequence');

const sessionId = `ctx-${Math.random().toString(36).substring(2, 11)}`;

let ws;
let currentFilter = 'all';
let selectedTraceId = null;
let selectedNodeId = 'manager';
let graphSvg = null;
let graphEdgesLayer = null;
let graphNodesLayer = null;
let networkMetadata = { nodes: {} };
let latestTokenSnapshot = null;
let pendingNewsRequest = null;
let newsReplySubmitting = false;

const eventHistory = [];
const traceMap = new Map();
const routingHistory = [];

const graphNodes = [
    { id: 'browser', label: 'Browser Client', role: 'User' },
    { id: 'manager', label: 'A2A Manager', role: 'Router' },
    { id: 'math', label: 'Math Specialist', role: 'Agent' },
    { id: 'weather', label: 'Weather Specialist', role: 'Agent' },
    { id: 'news', label: 'News Specialist', role: 'Agent' },
    { id: 'mcp', label: 'MCP Tooling', role: 'Tools' }
];

const graphConnections = [
    { id: 'browser-manager', from: 'browser', to: 'manager' },
    { id: 'manager-math', from: 'manager', to: 'math' },
    { id: 'manager-weather', from: 'manager', to: 'weather' },
    { id: 'manager-news', from: 'manager', to: 'news' },
    { id: 'math-mcp', from: 'math', to: 'mcp' },
    { id: 'weather-mcp', from: 'weather', to: 'mcp' }
];

function bootstrapGraph() {
    networkGraph.innerHTML = '';

    graphSvg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    graphSvg.classList.add('graph-edges');
    graphSvg.setAttribute('aria-hidden', 'true');

    graphEdgesLayer = document.createElementNS('http://www.w3.org/2000/svg', 'g');
    graphSvg.appendChild(graphEdgesLayer);

    graphNodesLayer = document.createElement('div');
    graphNodesLayer.className = 'graph-nodes-layer';

    graphNodes.forEach(node => {
        const el = document.createElement('button');
        el.className = 'graph-node';
        el.id = `graph-node-${node.id}`;
        el.dataset.nodeId = node.id;
        el.type = 'button';
        el.innerHTML = `<strong>${node.role}</strong>${node.label}`;
        el.addEventListener('click', () => {
            selectedNodeId = node.id;
            updateSelectedNodeState();
            renderNodeInspector();
        });
        graphNodesLayer.appendChild(el);
    });

    networkGraph.appendChild(graphSvg);
    networkGraph.appendChild(graphNodesLayer);

    renderGraphEdges();
    updateSelectedNodeState();

    window.addEventListener('resize', debounce(renderGraphEdges, 120));
}

function updateSelectedNodeState() {
    graphNodes.forEach(node => {
        const el = document.getElementById(`graph-node-${node.id}`);
        if (!el) return;
        el.classList.toggle('selected', selectedNodeId === node.id);
    });
}

function renderGraphEdges() {
    if (!graphSvg || !graphEdgesLayer) return;

    const graphRect = networkGraph.getBoundingClientRect();
    graphSvg.setAttribute('width', String(graphRect.width));
    graphSvg.setAttribute('height', String(graphRect.height));

    graphEdgesLayer.innerHTML = '';

    graphConnections.forEach(connection => {
        const fromEl = document.getElementById(`graph-node-${connection.from}`);
        const toEl = document.getElementById(`graph-node-${connection.to}`);
        if (!fromEl || !toEl) return;

        const fromRect = fromEl.getBoundingClientRect();
        const toRect = toEl.getBoundingClientRect();

        const x1 = fromRect.left + fromRect.width / 2 - graphRect.left;
        const y1 = fromRect.top + fromRect.height / 2 - graphRect.top;
        const x2 = toRect.left + toRect.width / 2 - graphRect.left;
        const y2 = toRect.top + toRect.height / 2 - graphRect.top;

        const line = document.createElementNS('http://www.w3.org/2000/svg', 'line');
        line.setAttribute('x1', String(x1));
        line.setAttribute('y1', String(y1));
        line.setAttribute('x2', String(x2));
        line.setAttribute('y2', String(y2));
        line.classList.add('graph-edge-line');
        line.id = `graph-edge-${connection.id}`;
        graphEdgesLayer.appendChild(line);
    });
}

function markGraphNodeActive(nodeId) {
    const node = document.getElementById(`graph-node-${nodeId}`);
    if (!node) return;
    node.classList.add('active');
    setTimeout(() => node.classList.remove('active'), 850);
}

function markGraphEdgeActive(edgeId) {
    const edge = document.getElementById(`graph-edge-${edgeId}`);
    if (!edge) return;
    edge.classList.add('active');
    setTimeout(() => edge.classList.remove('active'), 850);
}

function inferEdgesFromEvent(eventData) {
    const source = (eventData.source || '').toLowerCase();
    const payload = eventData.payload || {};

    const inferred = [];

    if (source.includes('browser')) {
        inferred.push('browser-manager');
    }

    if (source.includes('a2a server')) {
        inferred.push('browser-manager');
    }

    if (source.includes('a2a discovery client')) {
        const url = `${payload.url || ''}`.toLowerCase();
        if (url.includes('8001') || url.includes('math')) inferred.push('manager-math');
        if (url.includes('8002') || url.includes('weather')) inferred.push('manager-weather');
        if (url.includes('news-agent') || url.includes('news')) inferred.push('manager-news');
    }

    if (source.includes('a2a delegation client')) {
        const target = `${payload.target_url || ''}`.toLowerCase();
        if (target.includes('8001') || target.includes('math')) inferred.push('manager-math');
        if (target.includes('8002') || target.includes('weather')) inferred.push('manager-weather');
        if (target.includes('news-agent') || target.includes('news')) inferred.push('manager-news');
    }

    if (source.includes('mathspecialist')) inferred.push('manager-math');
    if (source.includes('weatherspecialist')) inferred.push('manager-weather');
    if (source.includes('newsspecialist')) inferred.push('manager-news');

    if (source.includes('mcp')) {
        inferred.push('math-mcp', 'weather-mcp');
    }

    return [...new Set(inferred)];
}

function trackGraphActivity(eventData) {
    const source = (eventData.source || '').toLowerCase();
    const type = (eventData.type || '').toLowerCase();

    if (source.includes('browser')) markGraphNodeActive('browser');
    if (source.includes('manager') || source.includes('a2a server') || source.includes('a2a discovery client') || source.includes('a2a delegation client')) {
        markGraphNodeActive('manager');
    }
    if (source.includes('math')) markGraphNodeActive('math');
    if (source.includes('weather')) markGraphNodeActive('weather');
    if (source.includes('news')) markGraphNodeActive('news');
    if (source.includes('mcp') || type.includes('tool')) markGraphNodeActive('mcp');

    inferEdgesFromEvent(eventData).forEach(markGraphEdgeActive);
}

function recentCallsForNode(nodeId) {
    const nodeMatchers = {
        browser: item => (item.source || '').toLowerCase().includes('browser'),
        manager: item => {
            const src = (item.source || '').toLowerCase();
            return src.includes('manager') || src.includes('a2a server') || src.includes('a2a discovery client') || src.includes('a2a delegation client');
        },
        math: item => (item.source || '').toLowerCase().includes('math'),
        weather: item => (item.source || '').toLowerCase().includes('weather'),
        news: item => (item.source || '').toLowerCase().includes('news'),
        mcp: item => (item.source || '').toLowerCase().includes('mcp')
    };

    const matcher = nodeMatchers[nodeId] || (() => false);

    return eventHistory
        .filter(matcher)
        .slice(-8)
        .reverse()
        .map(item => `${new Date(item.localTs).toLocaleTimeString()} | ${item.source} :: ${item.type}`);
}

function renderNodeInspector() {
    const nodeData = networkMetadata.nodes?.[selectedNodeId] || {};
    nodeInspector.innerHTML = '';

    const title = document.createElement('h4');
    title.className = 'node-inspector-title';
    title.textContent = nodeData.title || selectedNodeId;
    nodeInspector.appendChild(title);

    const desc = document.createElement('p');
    desc.className = 'node-inspector-desc';
    desc.textContent = nodeData.description || 'No metadata available for this node yet.';
    nodeInspector.appendChild(desc);

    if (nodeData.agent_card) {
        const section = document.createElement('div');
        section.className = 'node-inspector-section';
        const label = document.createElement('span');
        label.className = 'node-inspector-label';
        label.textContent = 'Agent Card';
        const pre = document.createElement('pre');
        pre.className = 'node-inspector-pre';
        pre.textContent = JSON.stringify(nodeData.agent_card, null, 2);
        section.appendChild(label);
        section.appendChild(pre);
        nodeInspector.appendChild(section);
    }

    if (nodeData.tool_schema) {
        const section = document.createElement('div');
        section.className = 'node-inspector-section';
        const label = document.createElement('span');
        label.className = 'node-inspector-label';
        label.textContent = `Tool Schema (${nodeData.tool_schema.server || 'MCP'})`;
        section.appendChild(label);

        const list = document.createElement('div');
        list.className = 'node-tool-list';
        (nodeData.tool_schema.tools || []).forEach(tool => {
            const row = document.createElement('div');
            row.className = 'node-tool-row';
            const args = Object.keys(tool.arguments || {}).length ? JSON.stringify(tool.arguments) : '{}';
            row.textContent = `${tool.name} ${args} - ${tool.description}`;
            list.appendChild(row);
        });
        section.appendChild(list);
        nodeInspector.appendChild(section);
    }

    if (nodeData.servers) {
        const section = document.createElement('div');
        section.className = 'node-inspector-section';
        const label = document.createElement('span');
        label.className = 'node-inspector-label';
        label.textContent = 'MCP Servers';
        section.appendChild(label);

        const list = document.createElement('div');
        list.className = 'node-tool-list';
        nodeData.servers.forEach(server => {
            const row = document.createElement('div');
            row.className = 'node-tool-row';
            row.textContent = `${server.name} (${server.module})`;
            list.appendChild(row);
        });
        section.appendChild(list);
        nodeInspector.appendChild(section);
    }

    const callsSection = document.createElement('div');
    callsSection.className = 'node-inspector-section';
    const callsLabel = document.createElement('span');
    callsLabel.className = 'node-inspector-label';
    callsLabel.textContent = 'Recent Calls';
    callsSection.appendChild(callsLabel);

    const calls = recentCallsForNode(selectedNodeId);
    if (!calls.length) {
        const empty = document.createElement('div');
        empty.className = 'node-tool-row';
        empty.textContent = 'No calls observed yet for this node.';
        callsSection.appendChild(empty);
    } else {
        const list = document.createElement('div');
        list.className = 'node-tool-list';
        calls.forEach(call => {
            const row = document.createElement('div');
            row.className = 'node-tool-row';
            row.textContent = call;
            list.appendChild(row);
        });
        callsSection.appendChild(list);
    }
    nodeInspector.appendChild(callsSection);
}

async function loadNetworkMetadata() {
    try {
        const response = await fetch('/api/demo/network');
        if (!response.ok) return;
        networkMetadata = await response.json();
    } catch (_error) {
        networkMetadata = { nodes: {} };
    }
    renderNodeInspector();
}

navChat.addEventListener('click', (e) => {
    e.preventDefault();
    navChat.classList.add('active');
    navArch.classList.remove('active');
    appUiContainer.style.display = 'flex';
    archContainer.style.display = 'none';
    setTimeout(renderGraphEdges, 50);
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
            handleIncomingEvent(data);
        } catch (e) {
            console.error('Failed to parse event data:', e);
        }
    };
}

function extractTraceId(eventData) {
    const payload = eventData.payload || {};

    if (payload.context_id) return payload.context_id;
    if (payload.contextId) return payload.contextId;
    if (payload.task_id) return payload.task_id;
    if (payload.params?.message?.contextId) return payload.params.message.contextId;
    if (payload.payload?.params?.message?.contextId) return payload.payload.params.message.contextId;
    if (payload.status?.context_id) return payload.status.context_id;

    return 'uncorrelated';
}

function inferRecentTraceId() {
    const now = Date.now();
    for (let i = eventHistory.length - 1; i >= 0; i -= 1) {
        const item = eventHistory[i];
        if (!item?.traceId || item.traceId === 'uncorrelated') continue;
        if (now - item.localTs > 20000) break;
        return item.traceId;
    }
    return null;
}

function humanizeAgentKey(key) {
    const map = {
        manager: 'Manager',
        mathspecialist: 'Math Specialist',
        math_specialist: 'Math Specialist',
        weatherspecialist: 'Weather Specialist',
        weather_specialist: 'Weather Specialist',
        newsspecialist: 'News Specialist',
        news_specialist: 'News Specialist'
    };
    return map[key] || key.replace(/_/g, ' ').replace(/\b\w/g, m => m.toUpperCase());
}

function setPendingNewsRequest(pending) {
    pendingNewsRequest = pending;
    renderNewsInbox();
}

function clearPendingNewsRequest() {
    pendingNewsRequest = null;
    newsReplySubmitting = false;
    renderNewsInbox();
}

function renderNewsInbox() {
    newsInboxCard.classList.toggle('active', Boolean(pendingNewsRequest));
    newsInboxStatus.textContent = newsReplySubmitting
        ? 'Sending'
        : pendingNewsRequest
            ? 'Awaiting Reply'
            : 'Idle';

    if (!pendingNewsRequest) {
        newsRequestBody.textContent = 'Waiting for the manager to delegate a news request.';
        newsResponseInput.value = '';
        newsResponseInput.disabled = true;
        return;
    }

    newsRequestBody.textContent = `[${pendingNewsRequest.task_id || 'pending'}] ${pendingNewsRequest.prompt || 'No prompt available.'}`;
    newsResponseInput.disabled = newsReplySubmitting;
    if (!newsReplySubmitting) newsResponseInput.focus();
}

async function loadPendingNewsRequest() {
    try {
        const response = await fetch('/api/news-agent/pending');
        if (!response.ok) return;
        const data = await response.json();
        setPendingNewsRequest(data.pending || null);
    } catch (_error) {
        setPendingNewsRequest(null);
    }
}

function renderTokenPanel(snapshot) {
    latestTokenSnapshot = snapshot;
    tokenStats.innerHTML = '';

    if (!snapshot || !snapshot.agents) {
        tokenStats.innerHTML = '<div class="token-placeholder">Waiting for model usage...</div>';
        return;
    }

    const rows = [];
    const byAgent = snapshot.agents || {};
    const priorityKeys = ['manager', 'mathspecialist', 'weatherspecialist', 'newsspecialist'];
    const seen = new Set();

    priorityKeys.forEach((key) => {
        rows.push([key, byAgent[key] || { input_tokens: 0, output_tokens: 0, total_tokens: 0, calls: 0 }]);
        seen.add(key);
    });

    Object.entries(byAgent).forEach(([key, value]) => {
        if (!seen.has(key)) rows.push([key, value]);
    });

    const overall = snapshot.overall || { total_tokens: 0, input_tokens: 0, output_tokens: 0, calls: 0 };
    rows.unshift(['overall', overall]);

    rows.forEach(([key, counters]) => {
        const label = key === 'overall' ? 'Overall' : humanizeAgentKey(key);
        const row = document.createElement('div');
        row.className = 'token-row';

        const labelEl = document.createElement('span');
        labelEl.className = 'token-label';
        labelEl.textContent = `${label} (${counters.calls || 0} calls)`;

        const valueEl = document.createElement('span');
        valueEl.className = 'token-value';
        const input = counters.input_tokens || 0;
        const output = counters.output_tokens || 0;
        const total = counters.total_tokens || 0;
        valueEl.textContent = `in ${input} | out ${output} | total ${total}`;

        row.appendChild(labelEl);
        row.appendChild(valueEl);
        tokenStats.appendChild(row);
    });
}

async function loadTokenMetrics() {
    try {
        const response = await fetch('/api/metrics/tokens');
        if (!response.ok) return;
        const data = await response.json();
        renderTokenPanel(data);
    } catch (_error) {
        renderTokenPanel(latestTokenSnapshot);
    }
}

function normalizeCategory(eventData) {
    const source = (eventData.source || '').toLowerCase();

    if (source.includes('mcp') || source.includes('fastmcp')) return 'mcp';
    return 'a2a';
}

function updateTraceMap(eventData, traceId, category) {
    if (!traceMap.has(traceId)) {
        traceMap.set(traceId, {
            id: traceId,
            firstSeen: Date.now(),
            lastSeen: Date.now(),
            count: 0,
            a2a: 0,
            mcp: 0,
            recent: ''
        });
    }

    const item = traceMap.get(traceId);
    item.lastSeen = Date.now();
    item.count += 1;
    item[category] += 1;
    item.recent = `${eventData.source} :: ${eventData.type}`;
}

function renderTraceCards() {
    if (!traceList) return;

    const traces = [...traceMap.values()].sort((a, b) => b.lastSeen - a.lastSeen);

    traceList.innerHTML = '';
    if (!traces.length) {
        traceList.innerHTML = '<div class="event-placeholder">No correlated requests yet.</div>';
        return;
    }

    traces.slice(0, 14).forEach(trace => {
        const card = document.createElement('div');
        card.className = `trace-card ${selectedTraceId === trace.id ? 'active' : ''}`;
        card.innerHTML = `
            <div class="trace-id">${trace.id}</div>
            <div class="trace-meta">${trace.count} events | A2A ${trace.a2a} | MCP ${trace.mcp}</div>
            <div class="trace-meta">${trace.recent}</div>
        `;
        card.addEventListener('click', () => {
            selectedTraceId = selectedTraceId === trace.id ? null : trace.id;
            renderTraceCards();
            renderTimeline();
            renderEventStream();
        });
        traceList.appendChild(card);
    });
}

function renderTimeline() {
    const rows = eventHistory
        .filter(event => !selectedTraceId || event.traceId === selectedTraceId)
        .slice(-40);

    timelineList.innerHTML = '';
    if (!rows.length) {
        timelineList.innerHTML = '<div class="event-placeholder">Timeline will populate with protocol events.</div>';
        return;
    }

    rows.forEach(item => {
        const row = document.createElement('div');
        row.className = 'timeline-row';

        const time = document.createElement('div');
        time.className = 'timeline-time';
        time.textContent = new Date(item.localTs).toLocaleTimeString();

        const desc = document.createElement('div');
        desc.className = 'timeline-desc';
        desc.textContent = `[${item.category.toUpperCase()}] ${item.source} -> ${item.type}`;

        row.appendChild(time);
        row.appendChild(desc);
        timelineList.appendChild(row);
    });

    timelineList.scrollTop = timelineList.scrollHeight;
}

function renderMetrics() {
    const total = eventHistory.length;
    const a2a = eventHistory.filter(e => e.category === 'a2a').length;
    const mcp = eventHistory.filter(e => e.category === 'mcp').length;

    const correlated = [...traceMap.values()].filter(t => t.id !== 'uncorrelated' && t.count > 1);
    const averageMs = correlated.length
        ? Math.round(correlated.reduce((acc, trace) => acc + (trace.lastSeen - trace.firstSeen), 0) / correlated.length)
        : 0;

    metricTotal.textContent = String(total);
    metricA2A.textContent = String(a2a);
    metricMCP.textContent = String(mcp);
    metricLatency.textContent = `${averageMs}ms`;
}

function renderArchitecturePanels() {
    archSequence.innerHTML = '';
    archRouting.innerHTML = '';

    const sequence = eventHistory.slice(-18);
    if (!sequence.length) {
        archSequence.textContent = 'Waiting for events...';
    } else {
        sequence.forEach(item => {
            const row = document.createElement('div');
            row.textContent = `${new Date(item.localTs).toLocaleTimeString()} | ${item.source} :: ${item.type}`;
            archSequence.appendChild(row);
        });
    }

    if (!routingHistory.length) {
        archRouting.textContent = 'No decisions yet.';
    } else {
        routingHistory.slice(-8).reverse().forEach(decision => {
            const row = document.createElement('div');
            row.textContent = `${decision.target} | ${decision.preview}`;
            archRouting.appendChild(row);
        });
    }
}

function renderEventStream() {
    const rows = eventHistory.filter(item => {
        const filterOk = currentFilter === 'all' || item.category === currentFilter;
        const traceOk = !selectedTraceId || item.traceId === selectedTraceId;
        return filterOk && traceOk;
    }).slice(-45);

    eventsList.innerHTML = '';
    if (!rows.length) {
        eventsList.innerHTML = '<div class="event-placeholder">No events match current filters.</div>';
        return;
    }

    rows.forEach(item => appendEventCard(item));
    eventsList.scrollTop = eventsList.scrollHeight;
}

function updateRoutingPanels(eventData) {
    if (eventData.type !== 'Routing Decision') return;
    const payload = eventData.payload || {};

    const target = payload.target_url || 'unknown-target';
    const preview = payload.task_preview || 'no task preview';

    routingRationale.querySelector('.rationale-text').textContent = `Delegating to ${target} | task: ${preview}`;

    routingHistory.push({ target, preview: preview.slice(0, 90) });
    if (routingHistory.length > 30) routingHistory.shift();
}

function updateNewsInboxFromEvent(eventData) {
    const source = (eventData.source || '').toLowerCase();
    if (!source.includes('newsspecialist')) return;

    if (eventData.type === 'Task Input Required') {
        const payload = eventData.payload || {};
        setPendingNewsRequest({
            request_id: payload.request_id,
            task_id: payload.task_id,
            context_id: payload.context_id,
            prompt: payload.prompt
        });
        return;
    }

    if (eventData.type === 'Task Completed' || eventData.type === 'Task Failed' || eventData.type === 'Human Reply Submitted') {
        clearPendingNewsRequest();
    }
}

function handleIncomingEvent(eventData) {
    if (eventData.source === 'Token Tracker' && eventData.type === 'Usage Update') {
        renderTokenPanel(eventData.payload);
        return;
    }

    const localTs = Date.now();
    const category = normalizeCategory(eventData);
    let traceId = extractTraceId(eventData);
    if (category === 'mcp' && traceId === 'uncorrelated') {
        const inferred = inferRecentTraceId();
        if (inferred) traceId = inferred;
    }

    const normalized = {
        ...eventData,
        localTs,
        category,
        traceId,
        eventId: `ev-${localTs}-${Math.random().toString(36).slice(2, 7)}`
    };

    eventHistory.push(normalized);
    if (eventHistory.length > 400) eventHistory.shift();

    updateTraceMap(normalized, traceId, category);
    updateRoutingPanels(normalized);
    updateNewsInboxFromEvent(normalized);
    trackGraphActivity(normalized);

    renderTraceCards();
    renderTimeline();
    renderEventStream();
    renderMetrics();
    renderArchitecturePanels();
    renderNodeInspector();
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
            jsonrpc: '2.0',
            id: `msg-${Date.now()}`,
            method: 'message/send',
            params: {
                message: {
                    messageId: `id-${Date.now()}`,
                    contextId: sessionId,
                    role: 'user',
                    parts: [{ text: message }]
                }
            }
        };

        handleIncomingEvent({
            source: 'Browser Client (A2A)',
            type: 'JSON-RPC Request',
            payload
        });

        const response = await fetch('/api/a2a/', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });

        const data = await response.json();

        handleIncomingEvent({
            source: 'A2A Server',
            type: 'JSON-RPC Response',
            payload: data
        });

        let messageText = null;
        if (data.error) {
            appendMessage(`A2A Error: ${data.error.message}`, 'system');
        } else {
            try {
                const payloadResult = data.result ? data.result : data;
                if (payloadResult.status?.message?.parts?.[0]?.text) {
                    messageText = payloadResult.status.message.parts[0].text;
                } else if (payloadResult.parts?.[0]?.text) {
                    messageText = payloadResult.parts[0].text;
                }
            } catch (_err) {
                messageText = 'Task completed.';
            }

            if (messageText) {
                let agentAvatar = 'AGT';
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

newsResponseForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    if (!pendingNewsRequest || newsReplySubmitting) return;

    const responseText = newsResponseInput.value.trim();
    if (!responseText) return;

    newsReplySubmitting = true;
    renderNewsInbox();

    try {
        const response = await fetch('/api/news-agent/respond', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                request_id: pendingNewsRequest.request_id,
                response_text: responseText
            })
        });
        const data = await response.json();

        if (!response.ok || !data.ok) {
            throw new Error(data.error || 'Failed to submit news response.');
        }

        newsResponseInput.value = '';
        clearPendingNewsRequest();
    } catch (err) {
        newsReplySubmitting = false;
        renderNewsInbox();
        appendMessage(`News agent reply failed: ${err.message}`, 'system');
    }
});

newsResponseInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        newsResponseForm.requestSubmit();
    }
});

filterBtns.forEach(btn => {
    btn.addEventListener('click', () => {
        filterBtns.forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        currentFilter = btn.dataset.filter;
        renderEventStream();
    });
});

async function copyTextToClipboard(text) {
    if (navigator.clipboard && window.isSecureContext) {
        await navigator.clipboard.writeText(text);
        return;
    }

    const textArea = document.createElement('textarea');
    textArea.value = text;
    textArea.style.position = 'fixed';
    textArea.style.left = '-9999px';
    document.body.appendChild(textArea);
    textArea.focus();
    textArea.select();
    document.execCommand('copy');
    textArea.remove();
}

function attachCopyBehavior(button, textGetter) {
    button.addEventListener('click', async () => {
        const originalText = button.textContent;
        try {
            await copyTextToClipboard(textGetter());
            button.textContent = 'Copied';
            button.classList.add('copied');
            setTimeout(() => {
                button.textContent = originalText;
                button.classList.remove('copied');
            }, 1000);
        } catch (_error) {
            button.textContent = 'Failed';
            setTimeout(() => {
                button.textContent = originalText;
            }, 1000);
        }
    });
}

function appendMessage(text, role, avatarText = null) {
    const msgDiv = document.createElement('div');
    msgDiv.className = `message ${role}-msg`;

    const avatar = document.createElement('div');
    avatar.className = 'msg-avatar';
    if (role === 'user') avatar.textContent = 'USR';
    else if (role === 'agent') avatar.textContent = avatarText || 'AGT';
    else avatar.textContent = 'SYS';

    const content = document.createElement('div');
    content.className = 'msg-content';
    content.innerHTML = marked.parse(text);

    if (window.renderMathInElement) {
        renderMathInElement(content, {
            delimiters: [
                { left: '$$', right: '$$', display: true },
                { left: '\\[', right: '\\]', display: true },
                { left: '$', right: '$', display: false },
                { left: '\\(', right: '\\)', display: false }
            ],
            throwOnError: false
        });
    }

    const contentWrap = document.createElement('div');
    contentWrap.className = 'msg-content-wrap';
    contentWrap.appendChild(content);

    if (role === 'user' || role === 'agent') {
        const copyBtn = document.createElement('button');
        copyBtn.className = 'copy-btn';
        copyBtn.type = 'button';
        copyBtn.textContent = 'Copy';
        attachCopyBehavior(copyBtn, () => text);
        contentWrap.appendChild(copyBtn);
    }

    msgDiv.appendChild(avatar);
    msgDiv.appendChild(contentWrap);
    chatWindow.appendChild(msgDiv);
    chatWindow.scrollTop = chatWindow.scrollHeight;
}

function appendEventCard(eventData) {
    const card = document.createElement('div');
    card.className = `event-card ${eventData.category}`;

    const header = document.createElement('div');
    header.className = 'event-card-header';

    const title = document.createElement('span');
    title.className = 'event-title';
    title.textContent = `${eventData.source} :: [${eventData.type}]`;

    const headerActions = document.createElement('div');
    headerActions.className = 'event-header-actions';

    const badge = document.createElement('span');
    badge.className = 'event-badge';
    badge.textContent = eventData.category;

    const copyBtn = document.createElement('button');
    copyBtn.className = 'copy-btn';
    copyBtn.type = 'button';
    copyBtn.textContent = 'Copy';
    attachCopyBehavior(copyBtn, () => JSON.stringify(eventData.payload, null, 2));

    headerActions.appendChild(badge);
    headerActions.appendChild(copyBtn);

    header.appendChild(title);
    header.appendChild(headerActions);

    const bodyContainer = document.createElement('div');
    bodyContainer.className = 'event-body';

    const meta = document.createElement('div');
    meta.className = 'event-body-meta';
    meta.textContent = describePayload(eventData.payload);

    const pre = document.createElement('pre');
    pre.textContent = formatPayload(eventData.payload);
    bodyContainer.appendChild(meta);
    bodyContainer.appendChild(pre);

    card.appendChild(header);
    card.appendChild(bodyContainer);
    eventsList.appendChild(card);
}

function formatPayload(payload) {
    if (payload === undefined) return '(no payload)';
    if (payload === null) return 'null';
    if (typeof payload === 'string') {
        const trimmed = payload.trim();
        if ((trimmed.startsWith('{') && trimmed.endsWith('}')) || (trimmed.startsWith('[') && trimmed.endsWith(']'))) {
            try {
                return JSON.stringify(JSON.parse(trimmed), null, 2);
            } catch (_error) {
                return payload;
            }
        }
        return payload;
    }

    try {
        return JSON.stringify(payload, getCircularSafeReplacer(), 2);
    } catch (_error) {
        return String(payload);
    }
}

function describePayload(payload) {
    if (payload === undefined) return 'payload: undefined';
    if (payload === null) return 'payload: null';
    if (typeof payload === 'string') return `payload: string (${payload.length} chars)`;
    if (Array.isArray(payload)) return `payload: array (${payload.length} items)`;
    if (typeof payload === 'object') return `payload: object (${Object.keys(payload).length} keys)`;
    return `payload: ${typeof payload}`;
}

function getCircularSafeReplacer() {
    const seen = new WeakSet();
    return (_key, value) => {
        if (typeof value === 'object' && value !== null) {
            if (seen.has(value)) return '[Circular]';
            seen.add(value);
        }
        return value;
    };
}

function debounce(fn, waitMs) {
    let timeoutId;
    return (...args) => {
        clearTimeout(timeoutId);
        timeoutId = setTimeout(() => fn(...args), waitMs);
    };
}

bootstrapGraph();
renderNodeInspector();
loadNetworkMetadata();
loadTokenMetrics();
loadPendingNewsRequest();
renderNewsInbox();
connectWebSocket();
