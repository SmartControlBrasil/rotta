import re


def normalize_document(value: str) -> str:
    """Removes all non-digit characters from the document string."""
    return re.sub(r"\D", "", value)


def validate_cpf(value: str) -> bool:
    """Validates a Brazilian CPF number (11 digits)."""
    clean_val = normalize_document(value)
    if len(clean_val) != 11:
        return False

    # Block common invalid CPFs (all digits identical)
    if clean_val == clean_val[0] * 11:
        return False

    # Calculate 1st digit
    s = 0
    for i in range(9):
        s += int(clean_val[i]) * (10 - i)
    digit1 = (s * 10) % 11
    if digit1 >= 10:
        digit1 = 0

    # Calculate 2nd digit
    s = 0
    for i in range(10):
        s += int(clean_val[i]) * (11 - i)
    digit2 = (s * 10) % 11
    if digit2 >= 10:
        digit2 = 0

    return int(clean_val[9]) == digit1 and int(clean_val[10]) == digit2


def validate_cnpj(value: str) -> bool:
    """Validates a Brazilian CNPJ number (14 digits)."""
    clean_val = normalize_document(value)
    if len(clean_val) != 14:
        return False

    # Block common invalid CNPJs (all digits identical)
    if clean_val == clean_val[0] * 14:
        return False

    # Weights for calculation
    weights1 = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    weights2 = [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]

    # Calculate 1st digit
    s = 0
    for i in range(12):
        s += int(clean_val[i]) * weights1[i]
    digit1 = 11 - (s % 11)
    if digit1 >= 10:
        digit1 = 0

    # Calculate 2nd digit
    s = 0
    for i in range(13):
        s += int(clean_val[i]) * weights2[i]
    digit2 = 11 - (s % 11)
    if digit2 >= 10:
        digit2 = 0

    return int(clean_val[12]) == digit1 and int(clean_val[13]) == digit2
