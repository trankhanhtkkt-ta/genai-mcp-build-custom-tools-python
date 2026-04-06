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


@mcp.resource("catalog://genres")
async def get_genres(ctx: Context) -> dict:
    """Get all available movie genres with their counts."""
    context = ctx.request_context.lifespan_context
    records, _, _ = await context.driver.execute_query(
        """
        MATCH (g:Genre)
        RETURN g.name AS name,
               count((g)<-[:IN_GENRE]-()) AS movieCount
        ORDER BY g.name
        """,
        database_=context.database
    )

    return {
        "genres": [
            dict(r) for r in records
        ]
    }


@mcp.resource("movie://{id}")
async def get_movie(id: str, ctx: Context) -> dict:
    """Get details about a specific movie by ID."""
    context = ctx.request_context.lifespan_context
    records, _, _ = await context.driver.execute_query(
        """
        MATCH (m:Movie {tmdbId: $id})
        RETURN m.title AS title,
                m.tagline AS tagline,
                m.released AS released,
                m.plot AS plot,
                [ (m)-[:IN_GENRE]->(g:Genre) | g.name ] AS genres
        """,
        id=id,
        database_=context.database
    )

    if not records:
        return {"error": f"Movie {id} not found"}

    return records[0].data()


@mcp.resource("movie://{tmdb_id}")
async def get_movie(tmdb_id: str, ctx: Context) -> str:
    """
    Get detailed information about a specific movie by TMDB ID.

    Args:
        tmdb_id: The TMDB ID of the movie (e.g., "603" for The Matrix)

    Returns:
        Formatted string with movie details including title, plot, cast, and genres
    """
    await ctx.info(f"Fetching movie details for TMDB ID: {tmdb_id}")

    context = ctx.request_context.lifespan_context

    try:
        records, _, _ = await context.driver.execute_query(
            """
            MATCH (m:Movie {tmdbId: $tmdb_id})
            RETURN m.title AS title,
               m.released AS released,
               m.tagline AS tagline,
               m.runtime AS runtime,
               m.plot AS plot,
               [ (m)-[:IN_GENRE]->(g:Genre) | g.name ] AS genres,
               [ (p)-[r:ACTED_IN]->(m) | {name: p.name, role: r.role} ] AS actors,
               [ (d)-[:DIRECTED]->(m) | d.name ] AS directors
            """,
            tmdb_id=tmdb_id,
            database_=context.database
        )

        if not records:
            await ctx.warning(f"Movie with TMDB ID {tmdb_id} not found")
            return f"Movie with TMDB ID {tmdb_id} not found in database"

        movie = records[0].data()

        # Format the output
        output = []
        output.append(f"# {movie['title']} ({movie['released']})")
        output.append("")

        if movie['tagline']:
            output.append(f"_{movie['tagline']}_")
            output.append("")

        output.append(f"**Runtime:** {movie['runtime']} minutes")
        output.append(f"**Genres:** {', '.join(movie['genres'])}")

        if movie['directors']:
            output.append(f"**Director(s):** {', '.join(movie['directors'])}")

        output.append("")
        output.append("## Plot")
        output.append(movie['plot'])

        if movie['actors']:
            output.append("")
            output.append("## Cast")
            for actor in movie['actors']:
                if actor['role']:
                    output.append(f"- {actor['name']} as {actor['role']}")
                else:
                    output.append(f"- {actor['name']}")

        result = "\n".join(output)

        await ctx.info(f"Successfully fetched details for '{movie['title']}'")

        return result

    except Exception as e:
        await ctx.error(f"Failed to fetch movie: {str(e)}")
        raise


@mcp.tool()
async def list_movies_paginated(
    cursor: str = "0",
    page_size: int = 50,
    ctx: Context = None
) -> dict:
    """
    List movies with pagination support.

    Args:
        cursor: Pagination cursor (skip value as string, default "0")
        page_size: Number of movies per page (default 50)

    Returns:
        Dictionary with 'movies' list and 'next_cursor' for next page
    """

    # Convert cursor to skip value
    skip = int(cursor)

    await ctx.info(f"Fetching movies {skip} to {skip + page_size}...")

    # Access driver
    driver = ctx.request_context.lifespan_context.driver

    # Query with SKIP and LIMIT
    records, summary, keys = await driver.execute_query(
        """
        MATCH (m:Movie)
        RETURN m.title AS title, m.released AS released
        ORDER BY m.title
        SKIP $skip
        LIMIT $limit
        """,
        skip=skip,
        limit=page_size
    )

    movies = [record.data() for record in records]

    # Calculate next cursor
    # If we got a full page, there might be more data
    next_cursor = None
    if len(movies) == page_size:
        next_cursor = str(skip + page_size)

    await ctx.info(f"Returned {len(movies)} movies")

    return {
        "movies": movies,
        "next_cursor": next_cursor,
        "current_page": skip // page_size,
        "page_size": page_size
    }


# Run the server when executed directly
if __name__ == "__main__":
    mcp.run(transport="streamable-http")
