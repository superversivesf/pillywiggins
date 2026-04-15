"""Roll dice and return the result."""

SKILL_META = {
    "name": "roll_dice",
    "description": "Roll one or more dice and return the results. Specify the number of dice and sides.",
    "author": "system",
    "version": "1.0",
    "parameters": {
        "num_dice": {"type": "integer", "description": "Number of dice to roll", "default": 1},
        "sides": {"type": "integer", "description": "Number of sides on each die", "default": 6},
    },
    "returns": "dict with rolls list and total",
    "permissions": {
        "network": False,
        "subprocess": False,
        "file_write": False,
    },
}

import random


async def run(num_dice: int = 1, sides: int = 6) -> dict:
    rolls = [random.randint(1, sides) for _ in range(num_dice)]
    return {"rolls": rolls, "total": sum(rolls)}