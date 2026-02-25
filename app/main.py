import sys
import os
import asyncio
import logging
import threading
import uvicorn
from multiprocessing import freeze_support

# Ensure project root is in sys.path for direct execution
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import config
from app import create_app
from app.state import state, tts_config
from app.services.tts import TTSService
from app.infrastructure.blcsdk import init_sdk, shut_down_sdk
from app.models import ParsedMessage


def _prewarm_tts_engine():
    """Pre-build the TTS engine pipeline in a background thread.
    This avoids a multi-second delay on the first TTS message.
    """
    try:
        from tts_engines.manager import tts_manager
        log = logging.getLogger('biliutility')
        log.info(f"[Startup] Pre-warming TTS engine: {tts_config.engine}...")
        engine = tts_manager.switch_engine(tts_config.engine)
        # switch_engine() only creates the engine object; pipeline is still lazy.
        # Explicitly call _ensure_pipeline() to actually build it now.
        if hasattr(engine, '_ensure_pipeline'):
            engine._ensure_pipeline()
            log.info("[Startup] Kokoro pipeline fully built and ready.")
        else:
            log.info("[Startup] TTS engine ready (no pipeline pre-build needed).")
    except Exception as e:
        logging.getLogger('biliutility').warning(
            f"[Startup] TTS pre-warm failed (will init on first use): {e}"
        )

# Configure logging
def init_logging():
    log_file = os.path.join(config.LOG_PATH, 'biliutility.log')
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(name)s] [%(levelname)s] %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(log_file, encoding='utf-8')
        ]
    )
    # Silence noise
    logging.getLogger('engineio').setLevel(logging.WARNING)
    logging.getLogger('socketio').setLevel(logging.WARNING)
    logging.getLogger('urllib3').setLevel(logging.WARNING)

# Standalone Entry Point
if __name__ == "__main__":
    freeze_support()
    init_logging()
    
    # Set mode
    config.IS_PLUGIN_MODE = False
    
    # Pre-warm TTS engine in background so first message plays instantly
    threading.Thread(target=_prewarm_tts_engine, daemon=True).start()
    
    app = create_app()
    
    uvicorn.run(
        app,
        host="127.0.0.1",
        port=config.FASTAPI_PORT,
        log_level="info"
    )

# Plugin Entry Point (called by loader)
async def run(args):
    init_logging()
    logging.info("Starting BiliUtility (Plugin Mode)...")
    
    # Set mode
    config.IS_PLUGIN_MODE = True
    
    # Callback for SDK messages
    async def on_sdk_message(msg: ParsedMessage):
        # Process TTS logic (translation etc)
        await TTSService.process_message_for_tts(msg)
        # Add to state (handles queues, gifts etc)
        await state.add_message(msg)
        
        # Broadcast to Frontend Widgets
        from app.routers.sockets import broadcast_message
        await broadcast_message(msg)

    # Initialize SDK
    await init_sdk(on_sdk_message)
    
    # Pre-warm TTS engine in background thread
    threading.Thread(target=_prewarm_tts_engine, daemon=True).start()
    
    # Create App
    app = create_app()
    
    # Configure Uvicorn server
    # Note: In plugin mode, we use FLASK_PORT (5001) as legacy?
    # Or should we use FASTAPI_PORT?
    # Existing users expect 5001.
    # We should probably use config.FLASK_PORT for plugin mode compatibility.
    port = config.FLASK_PORT
    
    config_uvicorn = uvicorn.Config(
        app=app,
        host="127.0.0.1",
        port=port,
        log_level="info"
    )
    server = uvicorn.Server(config_uvicorn)
    
    try:
        await server.serve()
    except asyncio.CancelledError:
        logging.info("Server cancelled")
    finally:
        shut_down_sdk()
