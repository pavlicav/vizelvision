"""Thursday Night Football on Prime Video: which NFL games it carries.

Finding and verifying the live game in the Prime Video app is TV Thing's
Roku lane's job since 2026-10-06; vizelVision only offers and schedules it.
"""
import re

SOURCE_ID = 'thursday-night-football'


def prime_nfl_game(game):
    return game.get('league') == 'nfl' and any(
        re.sub(r'[^a-z]', '', str(b.get('name', '')).lower()) in
        ('primevideo', 'amazonprime', 'amazonprimevideo', 'amazon', 'prime')
        for b in game.get('broadcasts', []) if isinstance(b, dict))
