const Chat = {
    init() {
        this.chatMessages = document.getElementById('chatMessages');
        this.chatWelcome = document.getElementById('chatWelcome');
        this.sendButton = document.getElementById('sendButton');
        this.uploadButton = document.getElementById('uploadButton');
        this.messageInput = document.getElementById('messageInput');
        this.healthBanner = document.getElementById('healthBanner');
        this.healthRetryBtn = document.getElementById('healthRetryBtn');
        this.isStreaming = false;
        this.currentResponse = null;
        this.ollamaReady = false;

        this.setupEventListeners();
        this.checkHealth();
    },

    setupEventListeners() {
        // Listeners for send/stop message button
        this.sendButton.addEventListener('click', () => {
            this.isStreaming ? this.handleStopGeneration() : this.handleSendMessage();
        });

        // Listeners for upload report button
        this.uploadButton.addEventListener('click', () => this.handleUploadReport());

        this.healthRetryBtn.addEventListener('click', () => this.checkHealth());

        document.addEventListener('keypress', (e) => {
            if (e.key === 'Enter' && !e.shiftKey && e.target.id === 'messageInput' && !this.isStreaming) {
                e.preventDefault();
                this.handleSendMessage();
            }
        });
    },

    async checkHealth() {
        try {
            const health = await AIService.getHealth();
            this.ollamaReady = health.ollama && !!health.chat_model;
            if (!health.ollama) {
                this.showBanner('Ollama is not reachable. Install Ollama, start it, and pull a model (e.g. "ollama pull qwen3").');
            } else if (!health.chat_model) {
                this.showBanner('No tool-capable model installed. Run "ollama pull qwen3" then retry.');
            } else {
                this.hideBanner();
            }
        } catch (error) {
            this.ollamaReady = false;
            this.showBanner('Backend unavailable. Restart the app.');
        }
        this.sendButton.disabled = !this.ollamaReady;
    },

    showBanner(text) {
        document.getElementById('healthBannerText').textContent = text;
        this.healthBanner.classList.remove('hidden');
    },

    hideBanner() {
        this.healthBanner.classList.add('hidden');
    },

    getInputValue() {
        return this.messageInput.value;
    },

    clearInput() {
        this.messageInput.value = '';
        UIManager.autoResizeTextarea();
    },

    hideWelcome() {
        if (this.chatWelcome && this.chatWelcome.style.display !== 'none') {
            this.chatWelcome.style.display = 'none';
        }
    },

    addUserMessage(text) {
        this.hideWelcome();
        this.chatMessages.appendChild(Message.createUserMessage(text));
    },

    addSystemMessage(text) {
        this.hideWelcome();
        this.chatMessages.appendChild(Message.createSystemMessage(text));
        UIManager.scrollToBottom();
    },

    async handleSendMessage() {
        const message = this.getInputValue();
        if (!message || !this.ollamaReady) return;

        this.addUserMessage(message);
        this.clearInput();
        this.setStreamingState(true);
        await this.getAIResponse(message);
    },

    handleStopGeneration() {
        if (this.currentResponse?.abort) {
            this.currentResponse.abort();
        }
        this.clearStreamingState();
        this.setStreamingState(false);
    },

    setStreamingState(isStreaming) {
        this.isStreaming = isStreaming;
        this.sendButton.classList.toggle('stop-button', isStreaming);
    },

    clearStreamingState() {
        this.currentResponse = null;
        this.chatMessages.querySelectorAll('.ai-message.streaming')
            .forEach(msg => msg.classList.remove('streaming'));
    },

    async handleUploadReport() {
        try {
            const selectResult = await UploadService.selectDirectory();
            if (!selectResult.success) return;

            const uploadResult = await UploadService.uploadReport(selectResult.directory_path);
            if (uploadResult.success) {
                this.addSystemMessage(`Report upload started (${uploadResult.job_name}). Processing runs in the background.`);
            } else {
                this.addSystemMessage(`Upload failed: ${uploadResult.detail || 'invalid LEAPP report directory'}`);
            }
        } catch (error) {
            console.error('Upload failed:', error);
            this.addSystemMessage('Upload failed: could not read the selected directory.');
        }
    },

    async getAIResponse(message) {
        this.hideWelcome();
        const streamingMessage = Message.createStreamingMessage();
        this.chatMessages.appendChild(streamingMessage);
        UIManager.scrollToBottom();

        try {
            const response = AIService.sendMessage(
                message,
                (event) => {
                    if (event.type === 'thinking') {
                        Message.appendThinking(streamingMessage, event.content);
                    } else if (event.type === 'token') {
                        Message.appendPendingToken(streamingMessage, event.content);
                    } else if (event.type === 'tool_call') {
                        Message.demotePendingToReasoning(streamingMessage);
                        Message.addToolChip(streamingMessage, event.name, event.arguments);
                    } else if (event.type === 'tool_result') {
                        Message.addToolResult(streamingMessage, event.name, event.success);
                    } else if (event.type === 'final') {
                        Message.setFinal(streamingMessage, event.content);
                    }

                    if (UIManager.shouldAutoScroll()) {
                        UIManager.scrollToBottom();
                    }
                },
                () => {
                    this.clearStreamingState();
                    this.setStreamingState(false);
                },
                (error) => {
                    Message.setErrorMessage(streamingMessage, error);
                    this.clearStreamingState();
                    this.setStreamingState(false);
                }
            );

            this.currentResponse = response;
            await response.promise;
        } catch (error) {
            console.error('Error in getAIResponse:', error);
            Message.setErrorMessage(streamingMessage, 'Sorry, there was an error processing your request.');
            this.clearStreamingState();
            this.setStreamingState(false);
        }
    }
};
