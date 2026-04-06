---
name: neo4j-mcp
displayName: Neo4j MCP Best Practices
description: Guidelines for working with Neo4j MCP server integration
keywords: neo4j, cypher, mcp, database, query
---

# Neo4j MCP Best Practices Skill

## Overview
This skill provides comprehensive guidance for working with Neo4j MCP server integration, including schema exploration, query development, and Python implementation patterns.

## Available Tools
- **neo4j_schema**: Get database schema (labels, relationships, properties)
- **neo4j_query**: Execute and validate Cypher queries

## Query Development Workflow

### Step 1: Schema Exploration
Always start by understanding the database structure:
```cypher
// Use neo4j_schema to explore available labels, relationships, and properties
```

### Step 2: Query Testing
Test your Cypher queries before implementation:
```cypher
MATCH (p:Person {name: $name})-[r:ACTED_IN]->(m:Movie)
RETURN m.title AS title, r.role AS role
ORDER BY m.title
LIMIT 100
```

### Step 3: Python Implementation
Implement with proper error handling and parameter binding:
```python
def find_movies_by_actor(driver, actor_name):
    """Find all movies for a given actor."""
    query = """
    MATCH (p:Person {name: $name})-[r:ACTED_IN]->(m:Movie)
    RETURN m.title AS title, r.role AS role
    ORDER BY m.title
    """
    try:
        with driver.session() as session:
            result = session.run(query, name=actor_name)
            return [dict(record) for record in result]
    except Exception as e:
        logging.error(f"Query failed: {e}")
        raise
```

## Best Practices

### Cypher Query Patterns
- **Avoid OPTIONAL MATCH** unless absolutely necessary. Use list comprehension in the RETURN clause instead
- Prefer explicit MATCH patterns with proper filtering
- Use list aggregation functions when dealing with optional relationships
- Always use parameters ($param) for dynamic values to prevent injection issues
- Add ORDER BY and LIMIT clauses for performance and predictability

### Python Implementation
- Include comprehensive error handling
- Add logging for debugging
- Use parameter binding for all variables
- Follow the workflow: schema → test → implement

### Performance Considerations
- Use LIMIT to prevent large result sets
- Order results for consistent output
- Index frequently queried properties
- Test queries on realistic data volumes

## Implementation Checklist
- [ ] Schema explored and understood
- [ ] Query tested and validated
- [ ] Parameters used for all variables
- [ ] ORDER BY and LIMIT applied
- [ ] Error handling implemented
- [ ] Logging added for debugging
- [ ] Python function follows best practices
