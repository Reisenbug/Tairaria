from __future__ import annotations

from terraria_agent.models.game_state import Camera, Player

TILE_SIZE = 16.0


def player_center_world(player: Player) -> tuple[float, float]:
    return (player.pos[0] + player.width / 2.0, player.pos[1] + player.height / 2.0)


def world_to_screen(world_xy: tuple[float, float], camera: Camera) -> tuple[int, int]:
    sx = (world_xy[0] - camera.screen_pos[0]) * camera.zoom
    sy = (world_xy[1] - camera.screen_pos[1]) * camera.zoom
    return (int(sx), int(sy))


def tile_offset_world(player: Player, dx_tiles: float, dy_tiles: float) -> tuple[float, float]:
    cx, cy = player_center_world(player)
    return (cx + dx_tiles * TILE_SIZE, cy + dy_tiles * TILE_SIZE)


def world_distance_tiles(a: tuple[float, float], b: tuple[float, float]) -> float:
    dx = (a[0] - b[0]) / TILE_SIZE
    dy = (a[1] - b[1]) / TILE_SIZE
    return (dx * dx + dy * dy) ** 0.5
