const Message = {
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

    // Content tokens stream into the answer area until we know whether they
    // precede a tool call (step text) or are the final answer
    appendPendingToken(messageElement, delta) {
        const answer = this._getAnswer(messageElement);
        answer.textContent += delta;
    },

    // A tool call arrived: whatever content streamed before it was step text,
    // not the answer, so move it into the reasoning section
    demotePendingToReasoning(messageElement) {
        const messageContent = messageElement.querySelector('.message-content');
        const answer = messageContent.querySelector('.final-answer-content');
        if (answer && answer.textContent) {
            const step = document.createElement('div');
            step.className = 'step-text';
            step.textContent = answer.textContent;
            this._getReasoning(messageElement).appendChild(step);
        }
        if (answer) answer.textContent = '';
    },

    addToolChip(messageElement, name, args) {
        const reasoning = this._getReasoning(messageElement);
        const chip = document.createElement('div');
        chip.className = 'tool-chip';
        chip.textContent = `→ ${name}(${JSON.stringify(args)})`;
        reasoning.appendChild(chip);
    },

    addToolResult(messageElement, name, success) {
        const reasoning = this._getReasoning(messageElement);
        const line = document.createElement('div');
        line.className = `tool-result ${success ? 'success' : 'failure'}`;
        line.textContent = success ? 'done' : 'failed';
        reasoning.appendChild(line);
    },

    // Authoritative final answer: render markdown and collapse the reasoning
    setFinal(messageElement, content) {
        const answer = this._getAnswer(messageElement);
        answer.innerHTML = marked.parse(content || '');

        const reasoning = messageElement.querySelector('.reasoning-container');
        if (reasoning) reasoning.classList.remove('expanded');

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
