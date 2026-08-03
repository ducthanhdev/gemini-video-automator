"""
Gói module tự động hóa Google Gemini / Veo Web UI.
Tách biệt trách nhiệm giữa TaskQueueManager, BrowserDriver, GeminiBot và Orchestrator.
"""

from backend.services.automation.orchestrator import AutomationManager

__all__ = ["AutomationManager"]
