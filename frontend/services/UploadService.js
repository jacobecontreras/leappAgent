const UploadService = {
    // Native folder picker exposed by pywebview
    async selectDirectory() {
        try {
            await this.waitForPywebview();
            return await window.pywebview.api.select_folder();
        } catch (error) {
            console.error('Directory selection failed:', error);
            throw error;
        }
    },

    waitForPywebview() {
        if (window.pywebview) return Promise.resolve();
        return new Promise((resolve, reject) => {
            window.addEventListener('pywebviewready', () => resolve(), { once: true });
            setTimeout(() => reject(new Error('pywebview API unavailable')), 3000);
        });
    },

    // Send the directory path for processing
    async uploadReport(directoryPath) {
        try {
            const response = await fetch('/api/upload', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ directory_path: directoryPath })
            });

            return await response.json();
        } catch (error) {
            console.error('Upload failed:', error);
            throw error;
        }
    }
};
