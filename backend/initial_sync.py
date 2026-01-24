import asyncio
import logging
import sys
import os

# Add the project root to sys.path
sys.path.append(os.path.join(os.getcwd(), 'backend'))

from app.services.scheduler_service import scheduler_service

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def run_sync():
    logger.info("Starting synchronization of stock history and fundamentals...")
    
    # Trigger the full sync logic from scheduler_service
    await scheduler_service.fetch_and_save_all_stocks_history()
    
    logger.info("Synchronization process finished.")

if __name__ == "__main__":
    asyncio.run(run_sync())
