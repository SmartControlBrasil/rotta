# src/freights/domain/exceptions.py
"""Domain exceptions for freights context."""

class InvalidFreightPricing(ValueError):
    """Raised when freight pricing invariants are violated."""
    pass
