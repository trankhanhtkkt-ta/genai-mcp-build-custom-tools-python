import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

from neo4j import AsyncGraphDatabase, AsyncDriver
from mcp.server.fastmcp import Context, FastMCP


# 1. Define a context class to hold your resources
@dataclass
class AppContext:
    """Application context with shared resources."""
    driver: AsyncDriver
    database: str


# 2. Create the lifespan context manager
@asynccontextmanager
async def app_lifespan(server: FastMCP) -> AsyncIterator[AppContext]:
    """Manage application lifecycle."""

    # Startup: Read credentials from environment variables
    uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
    username = os.getenv("NEO4J_USERNAME", "neo4j")
    password = os.getenv("NEO4J_PASSWORD", "password")
    database = os.getenv("NEO4J_DATABASE", "neo4j")

    # Initialize the Neo4j driver
    driver = AsyncGraphDatabase.driver(uri, auth=(username, password))

    try:
        # Yield the context with initialized resources
        yield AppContext(driver=driver, database=database)
    finally:
        # Shutdown: Clean up resources
        await driver.close()


# 3. Pass lifespan to the server
mcp = FastMCP("Movies GraphRAG Server", lifespan=app_lifespan)


# 4. Access the driver in your tools
@mcp.tool()
async def graph_statistics(ctx: Context) -> dict[str, int]:
    """Count the number of nodes and relationships in the graph."""

    # Access the driver from lifespan context
    driver = ctx.request_context.lifespan_context.driver

    # Use the driver to query Neo4j
    records, summary, keys = await driver.execute_query(
        "RETURN COUNT {()} AS nodes, COUNT {()-[]-()} AS relationships"
    )

    # Process the results
    if records:
        return dict(records[0])
    return {"nodes": 0, "relationships": 0}


# 5. Access the driver in your tools
@mcp.tool()
async def count_movie_nodes(ctx: Context) -> dict:
    """Count different types of nodes in the movie graph."""

    # Access the Neo4j driver from lifespan context
    driver = ctx.request_context.lifespan_context.driver

    # Initialize results
    results = {}

    # Define queries to run
    queries = [
        ("Person", "MATCH (p:Person) RETURN count(p) AS count"),
        ("Movie", "MATCH (m:Movie) RETURN count(m) AS count"),
        ("Genre", "MATCH (g:Genre) RETURN count(g) AS count"),
        ("User", "MATCH (u:User) RETURN count(u) AS count")
    ]

    # Log start of operation
    await ctx.info("Starting node count analysis...")

    # Execute each query and track progress
    for i, (label, query) in enumerate(queries):
        # Report progress (0-based index)
        await ctx.report_progress(
            progress=i,
            total=len(queries),
            message=f"Counting {label} nodes..."
        )

        # Execute query
        records, _, _ = await driver.execute_query(query)
        count = records[0]["count"]

        # Store and log result
        results[label] = count
        await ctx.info(f"Found {count} {label} nodes")

    # Report completion
    await ctx.report_progress(
        progress=len(queries),
        total=len(queries),
        message="Analysis complete!"
    )

    return results


@mcp.tool()
async def get_movies_by_genre(genre: str, limit: int = 10, ctx: Context = None) -> list[str]:
    """
    Get movies by genre from the Neo4j database.

    Args:
        genre: The genre to search for (e.g., "Action", "Drama", "Comedy")
        limit: Maximum number of movies to return (default: 10)
        ctx: Context object (injected automatically)

    Returns:
        List of movies with title, tagline, and release year
    """

    # Log the request
    await ctx.info(f"Searching for {genre} movies (limit: {limit})...")

    # Access the Neo4j driver from lifespan context
    driver = ctx.request_context.lifespan_context.driver

    # Log the query execution
    await ctx.debug(f"Executing Cypher query for genre: {genre}")

    try:
        # Execute the query
        records, summary, keys = await driver.execute_query(
            """
            MATCH (m:Movie)-[:IN_GENRE]->(g:Genre {name: $genre})
            RETURN m.title AS title,
                   m.imdbRating AS imdbRating,
                   m.released AS released
            ORDER BY coalesce(m.imdbRating, 0) DESC
            LIMIT $limit
            """,
            genre=genre,
            limit=limit
        )

        # Convert records to list of dictionaries
        movies = [record.data() for record in records]

        # Log the result
        await ctx.info(f"Found {len(movies)} {genre} movies")

        if len(movies) == 0:
            await ctx.warning(f"No movies found for genre: {genre}")

        return movies

    except Exception as e:
        # Log any errors
        await ctx.error(f"Query failed: {str(e)}")
        raise


# Run the server when executed directly
if __name__ == "__main__":
    mcp.run(transport="streamable-http")
