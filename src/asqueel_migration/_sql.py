"""SQL identifier quoting shared by migration writers and readers."""


def quote_identifier(name: str) -> str:
    """Quote one ANSI identifier, not a path or an authored SQL expression."""
    return '"' + name.replace('"', '""') + '"'
