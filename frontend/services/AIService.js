const AIService = {
    // Initialize or get existing session ID
    getSessionId() {
        let sessionId = localStorage.getItem('ai_leapp_session_id');
        if (!sessionId) {
            sessionId = 'session_' + Math.random().toString(36).substr(2, 9) + '_' + Date.now();
            localStorage.setItem('ai_leapp_session_id', sessionId);
        }
        return sessionId;
    },

    async getHealth() {
        const response = await fetch('/api/health');
        if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);
        return await response.json();
    },

    sendMessage(message, onEvent, onComplete, onError) {
        let aborted = false;
        const controller = new AbortController();
        const sessionId = this.getSessionId();

        const promise = (async () => {
            try {
                const response = await fetch('/api/chat', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    signal: controller.signal,
                    body: JSON.stringify({
                        message: message,
                        session_id: sessionId
                    })
                });

                if (!response.ok) {
                    throw new Error(`HTTP error! status: ${response.status}`);
                }

                const reader = response.body.getReader();
                const decoder = new TextDecoder();
                let buffer = '';

                try {
                    while (!aborted) {
                        const { done, value } = await reader.read();
                        if (done) break;

                        buffer += decoder.decode(value, { stream: true });
                        const lines = buffer.split('\n');
                        buffer = lines.pop() || '';

                        for (const line of lines) {
                            if (!line.startsWith('data: ')) continue;

                            const data = line.slice(6).trim();
                            if (data === '[DONE]') {
                                return;
                            }

                            try {
                                const parsed = JSON.parse(data);

                                if (parsed.type === 'error') {
                                    if (onError) onError(parsed.message);
                                    return;
                                }

                                if (parsed.type && onEvent) {
                                    onEvent(parsed);
                                }

                                if (parsed.done && onComplete) {
                                    onComplete();
                                }
                            } catch (e) {
                                // Skip invalid JSON silently
                            }
                        }
                    }
                } finally {
                    reader.releaseLock();
                }
            } catch (error) {
                if (error.name === 'AbortError' || aborted) {
                    return;
                }
                if (onError) onError(error.message);
                throw error;
            }
        })();

        return {
            promise: promise.catch(error => {
                if (!aborted && onError) onError(error.message);
                throw error;
            }),
            abort: () => {
                aborted = true;
                controller.abort();
            }
        };
    }
};
