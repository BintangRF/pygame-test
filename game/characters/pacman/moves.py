"""Pac-Man's move list: Chomp, Waka Rush, Bonus Fruit, Ghost Gang, Game
Over?, Warp Tunnel, Super Pac-Man. The numbers/tags here drive the generic combat
pipeline (core/combat_resolution.py); the behavior behind each tag lives in
plugin.py next to this file.

Passive (Waka Waka, see PacmanPlugin): the arena is one maze of pellets,
never refilled. Pac-Man roams like everyone else (nearby pellets slide to
him) and every few he eats charge his POWER meter and heal a little.
Clearing the whole maze powers him up once per match: the opponent is
frightened, and each bite chains 200 -> 400 -> 800 -> 1600 for more and
more damage, like eating ghosts."""

from ...core.abilities import Ability


def make_pacman_abilities():
    return {
        "basic": Ability("Chomp", "basic", "melee_dash", 0.9, 1.0, melee_range=100, tag="pac_chomp"),
        "skills": [
            # A straight full-speed chomp to the arena edge — biting anything
            # in the path, and sweeping up the pellets along the way.
            Ability("Waka Rush", "skill", "charge", 6, 1.3, tag="pac_rush"),
            # Sets this level's bonus fruit bouncing round the maze, Ms.
            # Pac-Man style: it bonks the opponent if they run into it, or
            # Pac-Man eats it himself for a heal and a POWER. Every cast
            # levels the fruit up (cherry -> ... -> key).
            Ability("Bonus Fruit", "skill", "cast", 5, 0.0, tag="pac_fruit", cast_target="self"),
            # All four ghosts out of the pen at once: they scatter to their
            # corners, then chase — each with its own arcade logic.
            Ability("Ghost Gang", "skill", "cast", 12, 0.0, tag="pac_ghost", cast_target="self"),
            # Plays dead (the death animation, untargetable), then pops up
            # behind the opponent for a surprise Chomp.
            Ability("Game Over?", "skill", "cast", 10, 0.0, tag="pac_fake", cast_target="self"),
            # Into the nearest wall, out of the opposite one — the maze's
            # wrap-around tunnel.
            Ability("Warp Tunnel", "skill", "cast", 9, 0.0, tag="pac_warp", cast_target="self"),
        ],
        # He grows giant, the opponent flees in terror, and he hunts it down
        # bite after bite.
        "ultimate": Ability("Super Pac-Man", "ultimate", "cast", 12, 0.0, big=True, tag="pac_super",
                            cast_target="self"),
    }
