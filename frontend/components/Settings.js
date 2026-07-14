const Settings = {
    init() {
        this.modal = document.getElementById('settingsModal');
        this.chatModelSelect = document.getElementById('chatModelSelect');
        this.embedModelSelect = document.getElementById('embedModelSelect');
        this.disableEmbeddingToggle = document.getElementById('disableEmbeddingToggle');
        this.clearDataBtn = document.getElementById('clearDataBtn');
        this.status = document.getElementById('settingsStatus');
        this.clearConfirmPending = false;

        document.getElementById('settingsButton').addEventListener('click', () => this.open());
        document.getElementById('settingsCloseBtn').addEventListener('click', () => this.close());
        this.modal.addEventListener('click', (e) => {
            if (e.target === this.modal) this.close();
        });

        this.chatModelSelect.addEventListener('change', () => this.save({ chat_model: this.chatModelSelect.value }));
        this.embedModelSelect.addEventListener('change', () => this.save({ embed_model: this.embedModelSelect.value }));
        this.disableEmbeddingToggle.addEventListener('change', () => this.save({ disable_embedding: this.disableEmbeddingToggle.checked }));
        this.clearDataBtn.addEventListener('click', () => this.clearData());
    },

    async open() {
        this.modal.classList.remove('hidden');
        this.setStatus('');
        await this.load();
    },

    close() {
        this.modal.classList.add('hidden');
        this.resetClearConfirm();
    },

    setStatus(text, isError = false) {
        this.status.textContent = text;
        this.status.classList.toggle('error', isError);
    },

    populateSelect(select, models, selected, emptyLabel) {
        select.innerHTML = '';
        if (!models.length) {
            const option = document.createElement('option');
            option.value = '';
            option.textContent = emptyLabel;
            select.appendChild(option);
            select.disabled = true;
            return;
        }
        select.disabled = false;
        for (const model of models) {
            const option = document.createElement('option');
            option.value = model.name;
            option.textContent = model.name;
            option.selected = model.name === selected;
            select.appendChild(option);
        }
    },

    async load() {
        try {
            const health = await AIService.getHealth();
            if (!health.ollama) {
                this.setStatus('Ollama is not reachable, model settings unavailable.', true);
            }
            this.populateSelect(this.chatModelSelect, health.models.filter(m => m.tools_capable),
                health.chat_model, 'No tool-capable models installed');
            this.populateSelect(this.embedModelSelect, health.models.filter(m => m.embedding),
                health.embed_model, 'No embedding models installed');

            const response = await fetch('/api/settings');
            const data = await response.json();
            if (data.success) {
                this.disableEmbeddingToggle.checked = !!data.settings.disable_embedding;
            }
        } catch (error) {
            console.error('Failed to load settings:', error);
            this.setStatus('Failed to load settings.', true);
        }
    },

    async save(settings) {
        try {
            const response = await fetch('/api/settings', {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(settings)
            });
            const data = await response.json();
            this.setStatus(data.success ? data.message : (data.detail || 'Failed to save settings.'), !data.success);
        } catch (error) {
            console.error('Failed to save settings:', error);
            this.setStatus('Failed to save settings.', true);
        }
    },

    resetClearConfirm() {
        this.clearConfirmPending = false;
        this.clearDataBtn.textContent = 'Clear Data';
    },

    // Two-click confirmation: native confirm() dialogs are unreliable in webviews
    async clearData() {
        if (!this.clearConfirmPending) {
            this.clearConfirmPending = true;
            this.clearDataBtn.textContent = 'Click again to confirm';
            setTimeout(() => this.resetClearConfirm(), 4000);
            return;
        }
        this.resetClearConfirm();

        try {
            const response = await fetch('/api/settings/clear-data', { method: 'POST' });
            const data = await response.json();
            this.setStatus(data.success ? 'All data cleared.' : 'Failed to clear data.', !data.success);
        } catch (error) {
            console.error('Failed to clear data:', error);
            this.setStatus('Failed to clear data.', true);
        }
    }
};
