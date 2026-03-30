"""
TikTok ETL Main Entry Point.

This module provides the main entry point for the TikTok ETL job,
using the class-based architecture for better organization and maintainability.
"""

import sys  # +
from typing import Optional

import typer
from loguru import logger

from client import TikTokAPIError, TikTokClient
from etl import TikTokETL
from utils import CLIENT_ID, CLIENT_SECRET, REFRESH_TOKEN


def main(
    start_date: str = typer.Option(
        ...,
        help="Start date for exporting accounts data (YYYY-MM-DD format).",
    ),
    end_date: str = typer.Option(
        ...,
        help="End date for exporting accounts data (YYYY-MM-DD format).",
    ),
    account_id: Optional[str] = typer.Option(
        None,
        help="Optional account ID. If not provided, will be fetched from account info.",
    ),
) -> None:
    """
    Main entry point for TikTok ETL job.

    Args:
        start_date: Start date for data extraction in YYYY-MM-DD format
        end_date: End date for data extraction in YYYY-MM-DD format
        business_id: Optional business ID. If not provided, will be fetched from account info
    """
    try:
        logger.info("Starting TikTok ETL job...")
        logger.info(f"Date range: {start_date} to {end_date}")

        # Initialize TikTok client
        client = TikTokClient(
            client_id=CLIENT_ID,
            client_secret=CLIENT_SECRET,
            refresh_token=REFRESH_TOKEN,
        )
    
        client.authenticate()  # raises on failure now, no return value check needed
        logger.info("Successfully authenticated with TikTok API")

        # Get account ID if not provided
        if not account_id:
            try:
                account_info = client.get_account_info()
                account_id = account_info["data"]["user"]["open_id"]
                logger.info(f"Retrieved account ID: {account_id}")
            except TikTokAPIError as e:
                raise RuntimeError(f"Failed to get account info: {e}") from e  # +

        # Initialize ETL processor
        etl_processor = TikTokETL(client)
        etl_processor.run_etl(  # raises on failure now, no return value check needed
            account_id=account_id, start_date=start_date, end_date=end_date
        )
        logger.info("TikTok ETL job completed successfully!")

    except Exception as e:
        logger.error(f"TikTok ETL job failed: {e}")
        sys.exit(1)  # +


if __name__ == "__main__":
    typer.run(main)
