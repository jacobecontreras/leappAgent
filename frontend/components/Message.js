const Message = {
    // Least-privilege policy for model-generated Markdown: only tags/attributes
    // marked emits from Markdown syntax; no images, SVG/MathML, styles, forms,
    // or id/name (DOM clobbering). Absolute http(s)/mailto URLs only.
    SANITIZE_CONFIG: {
        ALLOWED_TAGS: ['p', 'br', 'hr', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
                       'ul', 'ol', 'li', 'blockquote', 'pre', 'code',
                       'em', 'strong', 'del', 'a',
                       'table', 'thead', 'tbody', 'tr', 'th', 'td'],
        ALLOWED_ATTR: ['href', 'start', 'align'],
        ALLOWED_URI_REGEXP: /^(?:https?:|mailto:)/i,
        RETURN_DOM_FRAGMENT: true
    },

    // Sanitized Markdown rendering. Fails closed: returns null when DOMPurify
    // is unavailable or unsupported, and callers must fall back to textContent.
    renderMarkdown(text) {
        if (typeof DOMPurify === 'undefined' || DOMPurify.isSupported !== true) {
            return null;
        }
        try {
            const fragment = DOMPurify.sanitize(marked.parse(text || ''), this.SANITIZE_CONFIG);
            fragment.querySelectorAll('a').forEach(a => {
                a.setAttribute('target', '_blank');
                a.setAttribute('rel', 'noopener noreferrer');
            });
            return fragment;
        } catch (e) {
            return null;
        }
    },

    // Replace an element's children with sanitized rendered Markdown,
    // or the raw source as plain text if sanitization is unavailable
    renderInto(element, text) {
        const fragment = this.renderMarkdown(text);
        if (fragment) {
            element.replaceChildren(fragment);
        } else {
            element.textContent = text || '';
        }
    },

    // Used to render user messages in chat
    createUserMessage(text) {
        const messageDiv = document.createElement('div');
        messageDiv.className = 'message user-message';
        const content = document.createElement('div');
        content.className = 'message-content';
        content.textContent = text;
        messageDiv.appendChild(content);
        return messageDiv;
    },

    // Short informational messages (upload confirmations etc.)
    createSystemMessage(text) {
        const messageDiv = document.createElement('div');
        messageDiv.className = 'message system-message';
        messageDiv.textContent = text;
        return messageDiv;
    },

    // AI message shell: a collapsible reasoning section plus a final answer area
    createStreamingMessage() {
        const messageDiv = document.createElement('div');
        messageDiv.className = 'message ai-message streaming';
        messageDiv.innerHTML = '<div class="message-content"></div>';
        return messageDiv;
    },

    _getReasoning(messageElement) {
        const messageContent = messageElement.querySelector('.message-content');
        let container = messageContent.querySelector('.reasoning-container');
        if (!container) {
            container = document.createElement('div');
            container.className = 'reasoning-container expanded';

            const toggleButton = document.createElement('button');
            toggleButton.className = 'reasoning-toggle';
            toggleButton.textContent = 'Agent Process';
            toggleButton.onclick = () => container.classList.toggle('expanded');

            const content = document.createElement('div');
            content.className = 'reasoning-content';

            container.appendChild(toggleButton);
            container.appendChild(content);

            // Reasoning always renders above the answer area
            const answer = messageContent.querySelector('.final-answer-content');
            messageContent.insertBefore(container, answer || null);
        }
        return container.querySelector('.reasoning-content');
    },

    _getAnswer(messageElement) {
        const messageContent = messageElement.querySelector('.message-content');
        let answer = messageContent.querySelector('.final-answer-content');
        if (!answer) {
            answer = document.createElement('div');
            answer.className = 'final-answer-content';
            messageContent.appendChild(answer);
        }
        return answer;
    },

    // Model reasoning tokens (thinking-capable models)
    appendThinking(messageElement, delta) {
        const reasoning = this._getReasoning(messageElement);
        let block = reasoning.lastElementChild;
        if (!block || !block.classList.contains('thinking-text')) {
            block = document.createElement('div');
            block.className = 'thinking-text';
            reasoning.appendChild(block);
        }
        block.textContent += delta;
    },

    // Streaming render state per message element. The accumulated source
    // string is canonical; the DOM is only ever a rendering of it.
    RENDER_INTERVAL_MS: 100,
    _streamState: new WeakMap(),

    _getStreamState(messageElement) {
        let state = this._streamState.get(messageElement);
        if (!state) {
            state = { source: '', timer: null, lastRender: 0, settled: false };
            this._streamState.set(messageElement, state);
        }
        return state;
    },

    // Content tokens stream into the answer area until we know whether they
    // precede a tool call (step text) or are the final answer
    appendPendingToken(messageElement, delta) {
        const state = this._getStreamState(messageElement);
        state.source += delta;
        this._scheduleRender(messageElement, state);
    },

    _scheduleRender(messageElement, state) {
        if (state.settled || state.timer !== null) return;
        const wait = Math.max(0, this.RENDER_INTERVAL_MS - (performance.now() - state.lastRender));
        state.timer = setTimeout(() => {
            state.timer = null;
            if (state.settled) return;
            this._renderPending(messageElement, state);
        }, wait);
    },

    _renderPending(messageElement, state) {
        state.lastRender = performance.now();

        // Don't destroy an active selection inside the answer; the next tick
        // or the terminal render will catch up
        const answer = this._getAnswer(messageElement);
        const selection = document.getSelection();
        if (selection && !selection.isCollapsed && answer.contains(selection.anchorNode)) {
            this._scheduleRender(messageElement, state);
            return;
        }

        const shouldScroll = UIManager.shouldAutoScroll();
        this.renderInto(answer, state.source);
        if (shouldScroll) UIManager.scrollToBottom();
    },

    // A tool call arrived: whatever content streamed before it was step text,
    // not the answer, so move it into the reasoning section
    demotePendingToReasoning(messageElement) {
        const state = this._getStreamState(messageElement);
        if (state.source) {
            const step = document.createElement('div');
            step.className = 'step-text';
            step.textContent = state.source;
            this._getReasoning(messageElement).appendChild(step);
            state.source = '';
        }
        const answer = this._getAnswer(messageElement);
        answer.replaceChildren();
    },

    _cancelPendingRender(state) {
        if (state.timer !== null) {
            clearTimeout(state.timer);
            state.timer = null;
        }
    },

    addToolChip(messageElement, callId, name, args) {
        const reasoning = this._getReasoning(messageElement);
        const chip = document.createElement('div');
        chip.className = 'tool-chip';
        if (callId !== undefined) chip.dataset.callId = callId;
        chip.textContent = `→ ${name}(${JSON.stringify(args)})`;

        const status = document.createElement('span');
        status.className = 'tool-result running';
        status.textContent = 'running…';
        chip.appendChild(status);

        reasoning.appendChild(chip);
    },

    _setChipStatus(chip, statusClass, text) {
        const status = chip.querySelector('.tool-result');
        if (!status) return;
        status.className = `tool-result ${statusClass}`;
        status.textContent = text;
    },

    addToolResult(messageElement, callId, name, success) {
        const chip = callId !== undefined
            ? messageElement.querySelector(`.tool-chip[data-call-id="${callId}"]`)
            : null;
        if (chip) {
            this._setChipStatus(chip, success ? 'success' : 'failure', success ? 'done' : 'failed');
            return;
        }
        // Result without a matching chip (should not happen): keep it visible
        const line = document.createElement('div');
        line.className = `tool-result ${success ? 'success' : 'failure'}`;
        line.textContent = success ? 'done' : 'failed';
        this._getReasoning(messageElement).appendChild(line);
    },

    // No chip may remain "running…" after settlement
    _sweepRunningChips(messageElement, reason) {
        const label = reason === 'aborted' ? 'stopped'
            : (reason === 'complete' ? 'unknown' : 'interrupted');
        messageElement.querySelectorAll('.tool-chip .tool-result.running').forEach(status => {
            status.className = 'tool-result failure';
            status.textContent = label;
        });
    },

    // Authoritative final answer: render markdown and collapse the reasoning
    setFinal(messageElement, content) {
        const state = this._getStreamState(messageElement);
        this._cancelPendingRender(state);
        state.settled = true;

        const answer = this._getAnswer(messageElement);
        this.renderInto(answer, content);

        const reasoning = messageElement.querySelector('.reasoning-container');
        if (reasoning) reasoning.classList.remove('expanded');

        messageElement.classList.remove('streaming');
    },

    _appendNote(messageElement, text) {
        const note = document.createElement('div');
        note.className = 'stream-note';
        note.textContent = text;
        messageElement.querySelector('.message-content').appendChild(note);
    },

    // Terminal settlement: exactly one call per message; renders any pending
    // source, labels the outcome, and freezes the message against further
    // render ticks. `result` is AIService's settlement object.
    finalizeStream(messageElement, result) {
        const state = this._getStreamState(messageElement);
        this._cancelPendingRender(state);
        state.settled = true;

        // final already rendered authoritatively via setFinal
        if (!result.receivedFinal && state.source) {
            this.renderInto(this._getAnswer(messageElement), state.source);
        }

        if (result.reason === 'error') {
            this.setErrorMessage(messageElement, result.errorMessage || 'Unknown error');
        } else if (result.reason === 'incomplete') {
            this._appendNote(messageElement, 'Response ended unexpectedly and may be incomplete.');
        } else if (result.reason === 'aborted') {
            this._appendNote(messageElement, 'Stopped.');
        } else if (result.reason === 'complete' && result.malformedCount > 0) {
            this._appendNote(messageElement, 'Some response data could not be read.');
        }

        this._sweepRunningChips(messageElement, result.reason);
        messageElement.classList.remove('streaming');
    },

    // Used to render error messages in chat
    setErrorMessage(messageElement, errorText) {
        const messageContent = messageElement.querySelector('.message-content');
        const error = document.createElement('div');
        error.className = 'error-text';
        error.textContent = errorText;
        messageContent.appendChild(error);
        messageElement.classList.remove('streaming');
    }
};
