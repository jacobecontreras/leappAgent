import logging
from typing import Dict, Any
from database.database import get_ai_setting, set_ai_setting

logger = logging.getLogger(__name__)

class SettingsService:
    """Service for managing AI settings stored in database"""

    def get_all_settings(self) -> Dict[str, Any]:
        """Get all AI settings as a dictionary"""
        return {
            'chat_model': self.get_chat_model(),
            'embed_model': self.get_embed_model(),
            'disable_embedding': self.get_disable_embedding()
        }

    def get_chat_model(self) -> str:
        """Get the stored chat model"""
        return get_ai_setting('chat_model') or ''

    def get_embed_model(self) -> str:
        """Get the stored embedding model"""
        return get_ai_setting('embed_model') or ''

    def get_disable_embedding(self) -> bool:
        """Get the disable_embedding setting"""
        return get_ai_setting('disable_embedding') == 'true'

    def set_chat_model(self, model: str):
        """Set the chat model"""
        set_ai_setting('chat_model', model)
        logger.info(f"Chat model updated to: {model}")

    def set_embed_model(self, model: str):
        """Set the embedding model"""
        set_ai_setting('embed_model', model)
        logger.info(f"Embedding model updated to: {model}")

    def set_disable_embedding(self, disable: bool):
        """Set the disable_embedding setting"""
        set_ai_setting('disable_embedding', str(disable).lower())
        logger.info(f"Disable embedding updated to: {disable}")

    def update_settings(self, settings: Dict[str, Any]) -> bool:
        """Update multiple settings at once"""
        try:
            if 'chat_model' in settings:
                self.set_chat_model(settings['chat_model'])

            if 'embed_model' in settings:
                self.set_embed_model(settings['embed_model'])

            if 'disable_embedding' in settings:
                self.set_disable_embedding(settings['disable_embedding'])

            return True
        except Exception as e:
            logger.error(f"Error updating settings: {e}")
            return False

# Global instance
settings_service = SettingsService()
