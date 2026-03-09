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

async def _run_plugin_mode():
    """Plugin entry: connect to blivechat via SDK, then start our own uvicorn server."""
    logging.info("Starting BiliUtility (Plugin Mode)...")

    # Callback for SDK messages
    async def on_sdk_message(msg: ParsedMessage):
        # Process TTS logic (translation etc)
        await TTSService.process_message_for_tts(msg)
        # Add to state (handles queues, gifts etc)
        await state.add_message(msg)

        # Broadcast to Frontend Widgets
        from app.routers.sockets import broadcast_message
        await broadcast_message(msg)

    # Initialize SDK — reads BLC_PORT / BLC_TOKEN env vars automatically
    await init_sdk(on_sdk_message)

    # Create App
    app = create_app()

    # Configure Uvicorn server
    # NOTE: blivechat itself occupies its own port (e.g. 12450).
    # We always use FASTAPI_PORT (5149) to avoid the collision.
    port = config.FASTAPI_PORT
    logging.info(f"[Startup] Plugin mode server starting on port {port}")

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
        await shut_down_sdk()


# Unified Entry Point
if __name__ == "__main__":
    freeze_support()
    init_logging()

    # Pre-warm TTS engine in background so first message plays instantly
    threading.Thread(target=_prewarm_tts_engine, daemon=True).start()

    if os.environ.get('BLC_PORT'):
        # Plugin Mode: launched by blivechat (BLC_PORT env var is set)
        config.IS_PLUGIN_MODE = True
        asyncio.run(_run_plugin_mode())
    else:
        # Standalone Mode: direct launch (no blivechat)
        config.IS_PLUGIN_MODE = False
        app = create_app()
        uvicorn.run(
            app,
            host="127.0.0.1",
            port=config.FASTAPI_PORT,
            log_level="info"
        )
