import asyncio
import random
from datetime import datetime
from typing import List, Optional
from ..core.database import Database
from ..core.models import Character, Token
from ..core.logger import debug_logger
from .sora_client import SoraClient
from .proxy_manager import ProxyManager

class CharacterManager:
    """Manager for Character validation (Legacy library management removed)"""
    
    def __init__(self, db: Database):
        self.db = db
        self.proxy_manager = ProxyManager(db)
        self.client = SoraClient(self.proxy_manager)
        
    async def validate_character(self, sora_character_id: str) -> bool:
        """Validate a character's availability directly via Sora API
        
        Args:
            sora_character_id: The Sora Character ID (e.g. ch_...)
            
        Returns:
            True if valid, False if invalid/not found
        """
        all_tokens = await self.db.get_active_tokens()
        if not all_tokens:
            debug_logger.log_error("[CharacterManager] No active tokens available for validation")
            return False
            
        # Pick a random token for validation
        random_token = random.choice(all_tokens).token
        
        try:
            debug_logger.log_info(f"[CharacterManager] Validating character {sora_character_id}...")
            # Try to get character details
            details = await self.client.get_character_details(sora_character_id, random_token)
            
            if not details:
                return False
                
            # Check if returned ID matches requested ID
            returned_id = details.get("id")
            # Sometimes details might be wrapped or structure differs, but get_character_details usually returns the dict
            if returned_id == sora_character_id:
                debug_logger.log_info(f"[CharacterManager] Character {sora_character_id} is VALID")
                return True
                
            # Double check if it's inside 'character' key
            char_data = details.get("character", {})
            if char_data.get("id") == sora_character_id:
                debug_logger.log_info(f"[CharacterManager] Character {sora_character_id} is VALID (nested)")
                return True
                
            debug_logger.log_warning(f"[CharacterManager] Character {sora_character_id} ID mismatch. Got: {returned_id}")
            return False
            
        except Exception as e:
            if "404" in str(e):
                 debug_logger.log_info(f"[CharacterManager] Character {sora_character_id} not found (404)")
                 return False
            
            debug_logger.log_error(f"[CharacterManager] Validation failed for {sora_character_id}: {e}", 500)
            return False
