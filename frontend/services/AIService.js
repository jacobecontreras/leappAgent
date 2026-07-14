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

    // Streams a chat response. Settlement fires exactly once per request:
    // onSettled({reason, errorMessage, receivedFinal, malformedCount}) with
    // reason one of 'complete' | 'incomplete' | 'error' | 'aborted'.
    // The returned promise always resolves with the same object.
    sendMessage(message, onEvent, onSettled) {
        let aborted = false;
        const controller = new AbortController();
        const sessionId = this.getSessionId();

        let settled = null;
        let receivedFinal = false;
        let malformedCount = 0;

        const settle = (reason, errorMessage) => {
            if (settled) return settled;
            settled = {
                reason,
                errorMessage: errorMessage || null,
                receivedFinal,
                malformedCount
            };
            if (onSettled) onSettled(settled);
            return settled;
        };

        // Processes one SSE line. Returns a settlement object when the line
        // is terminal, otherwise null.
        const processLine = (line) => {
            if (!line.startsWith('data: ')) return null;

            const data = line.slice(6).trim();
            if (data === '[DONE]') {
                return settle(receivedFinal ? 'complete' : 'incomplete');
            }

            let parsed;
            try {
                parsed = JSON.parse(data);
            } catch (e) {
                malformedCount++;
                console.warn('Unparseable stream event:', data.slice(0, 200));
                return null;
            }

            if (parsed.type === 'error') {
                return settle('error', parsed.message);
            }

            // A stray render event after the authoritative final must not
            // mutate the answer
            if (receivedFinal && ['token', 'thinking', 'tool_call'].includes(parsed.type)) {
                console.warn('Ignoring post-final event:', parsed.type);
                return null;
            }

            if (parsed.type === 'final') {
                receivedFinal = true;
            }

            if (parsed.type && onEvent) {
                onEvent(parsed);
            }

            if (parsed.done) {
                return settle(receivedFinal ? 'complete' : 'incomplete');
            }
            return null;
        };

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
                            if (processLine(line)) return settled;
                        }
                    }

                    // EOF: flush the decoder's multibyte tail and classify
                    // whatever is still buffered
                    buffer += decoder.decode();
                    const tail = buffer.trim();
                    if (tail) {
                        if (tail.startsWith('data: ')) {
                            // Might be a complete buffered event (e.g. final
                            // without a trailing newline); a truncated one
                            // counts as malformed inside processLine
                            if (processLine(tail)) return settled;
                        } else {
                            malformedCount++;
                            console.warn('Truncated stream data at EOF:', tail.slice(0, 200));
                        }
                    }
                } finally {
                    reader.releaseLock();
                }

                if (aborted) {
                    return settle(receivedFinal ? 'complete' : 'aborted');
                }
                return settle(receivedFinal ? 'complete' : 'incomplete');
            } catch (error) {
                if (error.name === 'AbortError' || aborted) {
                    return settle(receivedFinal ? 'complete' : 'aborted');
                }
                return settle('error', error.message);
            }
        })();

        return {
            promise,
            abort: () => {
                aborted = true;
                controller.abort();
            }
        };
    }
};
