"""
This module registers the web search tools with the MCP server.

It provides two distinct web search implementations:
1.  **API-based:** Uses the Brave Search API for reliable, structured results.
    This is the preferred method.
2.  **Scraping-based:** Uses Playwright and BeautifulSoup to scrape search
    engine results. This is less reliable and should be used as a fallback.
"""
from fastmcp import FastMCP, Context
from ..state_manager import create_session_if_not_exists
from ...logger_config import get_logger
import uuid
from typing import Dict, Any, List, Optional
import asyncio
import os
import httpx

# Playwright imports
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError

# Use the centralized logger
logger = get_logger(__name__)

# --- Session Management Helpers (adapt if session context is needed for websearch) ---
async def ensure_session_initialized_websearch(ctx: Context) -> str:
    """Helper to ensure the session exists in the database."""
    session_id = get_stable_session_id_websearch(ctx)
    client_id = ctx.client_id if hasattr(ctx, 'client_id') else None
    await create_session_if_not_exists(session_id, client_id)
    return session_id

def get_stable_session_id_websearch(ctx: Context) -> str:
    """Retrieves or generates a stable session ID for the websearch tool context."""
    if hasattr(ctx, 'session_id') and ctx.session_id:
        return ctx.session_id
    if ctx.request_id:
        return ctx.request_id
    logger.warning("WebSearch Tool: Could not determine a stable session ID. Generating a new one.")
    return str(uuid.uuid4())

def _parse_html_with_beautifulsoup(html_content: str) -> List[Dict[str, str]]:
    """Parses HTML content from a search engine results page using BeautifulSoup."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html_content, "lxml")
    results = []

    # Define selector strategies for BeautifulSoup.
    selector_strategies = [
        {
            "name": "React-based DDG",
            "container": "ol.react-results--main",
            "entry": "article",
            "title": 'a[data-testid="result-title-a"]',
            "snippet": 'div[data-testid="result-snippet"]',
        },
        {
            "name": "HTML-based DDG",
            "container": "#links",
            "entry": "div.result",
            "title": "h2.result__title > a.result__a",
            "snippet": "a.result__snippet",
        }
    ]

    found_container = None
    strategy_used = None
    for strategy in selector_strategies:
        container = soup.select_one(strategy["container"])
        if container:
            found_container = container
            strategy_used = strategy
            logger.info(f"Parser: Found search results container using strategy '{strategy['name']}'.")
            break
    
    if not found_container or not strategy_used:
        logger.warning("Parser: Could not find a known search results container in the HTML.")
        return []

    search_entries = found_container.select(strategy_used["entry"])
    logger.info(f"Parser: Found {len(search_entries)} search result elements.")

    for entry in search_entries:
        title_element = entry.select_one(strategy_used["title"])
        snippet_element = entry.select_one(strategy_used["snippet"])
        
        title = title_element.get_text(strip=True) if title_element else "N/A"
        link = title_element.get("href") if title_element else "N/A"
        snippet = snippet_element.get_text(strip=True) if snippet_element else "N/A"

        if title and link and title != "N/A":
            results.append({"title": title, "link": link, "snippet": snippet})
            
    return results

async def _render_page_with_playwright(query: str, search_engine_url: str, wait_timeout: int) -> str:
    """Renders a search page using Playwright and returns its HTML content."""
    html_content = ""
    async with async_playwright() as p:
        browser = None
        try:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            logger.info(f"Playwright: Navigating to: {search_engine_url}?q={query}")
            await page.goto(f"{search_engine_url}?q={query}", wait_until="domcontentloaded")

            await page.wait_for_selector("body", timeout=wait_timeout * 1000)
            html_content = await page.content()
            logger.info(f"Playwright: Successfully retrieved HTML content of size {len(html_content)}.")
        except PlaywrightTimeoutError as te:
            screenshot_path = f"/tmp/playwright_fail_{uuid.uuid4()}.png"
            if 'page' in locals() and not page.is_closed():
                await page.screenshot(path=screenshot_path)
                logger.error(f"Playwright search timed out after {wait_timeout}s. Screenshot saved to {screenshot_path}", exc_info=True)
            raise RuntimeError(f"Playwright timed out after {wait_timeout}s waiting for page to load. Original error: {te}") from te
        except Exception as e:
            logger.error(f"Playwright search failed: {type(e).__name__} - {e}", exc_info=True)
            raise RuntimeError(f"Playwright execution failed: {type(e).__name__} - {e}") from e
        finally:
            if browser:
                await browser.close()
                logger.info("Playwright: Browser closed.")
    return html_content

async def _run_brave_search_api(query: str, num_results: int, timeout: int = 20) -> List[Dict[str, str]]:
    """Performs a web search using the Brave Search API."""
    api_key = os.getenv("BRAVE_SEARCH_API_KEY")
    if not api_key:
        logger.error("BRAVE_SEARCH_API_KEY environment variable not set. Web search is unavailable.")
        raise ValueError("The Brave Search API key is not configured on the server.")

    headers = {"Accept": "application/json", "X-Subscription-Token": api_key}
    params = {"q": query, "count": num_results}
    api_url = "https://api.search.brave.com/res/v1/web/search"

    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.get(api_url, headers=headers, params=params)
        response.raise_for_status()
        data = response.json()

        results = []
        for item in data.get("web", {}).get("results", []):
            results.append({
                "title": item.get("title"),
                "link": item.get("url"),
                "snippet": item.get("description"),
            })
        return results

def register_tools(mcp: FastMCP):
    """Registers the web search tools with the MCP server."""
    @mcp.tool()
    async def perform_web_search_api(query: str, ctx: Context, num_results: int = 5, timeout: int = 20, mcp_session_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Performs a web search using the Brave Search API. This is the
        recommended, most robust method.
        """
        logger.info(f"Web search tool called with query: '{query}', num_results: {num_results}, timeout: {timeout}")
        session_id = await ensure_session_initialized_websearch(ctx) 
        #session_id = mcp_session_id or "default"
        
        await ctx.info(f"Session {session_id}: Performing web search for: '{query}' via Brave Search API")

        try:
            search_results = await _run_brave_search_api(query, num_results, timeout=timeout)

            if not search_results:
                await ctx.warning(f"No search results found for query: '{query}'")
                return {"query": query, "results": [], "message": "No results found."}
            
            await ctx.info(f"Found {len(search_results)} results for query: '{query}'")
            return {"query": query, "results": search_results}
        except ValueError as e:
            logger.error(f"Web search configuration error: {e}")
            await ctx.error(f"Web search failed: {e}")
            return {"error": f"Web search tool is not configured correctly on the server: {e}"}
        except Exception as e:
            logger.error(f"Error during web search for query '{query}': {e}", exc_info=True)
            await ctx.error(f"Web search failed: {e}")
            return {"error": f"Failed to perform web search: {e}"}

    @mcp.tool()
    async def perform_web_search_scraping(query: str, ctx: Context, num_results: int = 5, timeout: int = 20, mcp_session_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Performs a web search by scraping a search engine's website.
        Less reliable than the API version. Use for demonstration or as a fallback.
        """
        
        logger.info(f"Web search tool (perform_web_search_scraping) called with query: '{query}', num_results: {num_results}, timeout: {timeout}")
        session_id = await ensure_session_initialized_websearch(ctx) 
        #session_id = mcp_session_id or "default"
        await ctx.info(f"Session {session_id}: Performing web search for: '{query}' via scraping")
        
        search_engine_url = os.getenv("SEARCH_ENGINE_URL", "https://duckduckgo.com/")

        try:
            html_content = await _render_page_with_playwright(query, search_engine_url, timeout)
            if not html_content:
                raise RuntimeError("Playwright failed to retrieve HTML content.")

            parsed_results = await asyncio.to_thread(_parse_html_with_beautifulsoup, html_content)
            search_results = parsed_results[:num_results]
            
            if not search_results:
                await ctx.warning(f"No search results found for query: '{query}'")
                return {"query": query, "results": [], "message": "No results found."}
            
            await ctx.info(f"Found {len(search_results)} results for query: '{query}'")
            return {"query": query, "results": search_results}
        except RuntimeError as e:
            # This catches the specific errors raised from within _render_page_with_playwright
            logger.error(f"Error during Playwright execution for query '{query}': {e}", exc_info=True)
            await ctx.error(f"Web scraping failed: {e}")
            return {"status": "error", "message": f"Failed to perform web search via scraping: {e}"}
        except Exception as e:
            logger.error(f"Error during scraping web search for query '{query}': {e}", exc_info=True)
            await ctx.error(f"Scraping web search failed: {e}")
            return {"status": "error", "message": f"An unexpected error occurred during scraping web search: {e}"}
            
    logger.info("Web search MCP tools (API and Scraping) registered.")