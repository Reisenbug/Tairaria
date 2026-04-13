from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Optional

from terraria_agent.cerebellum.damage_detector import DamageDetector
from terraria_agent.geometry import player_center_world, world_distance_tiles
from terraria_agent.models.game_state import (
    Camera, DroppedItem, Enemy, EnemyThreat, GameState, InventorySlot,
    MovementInfo, Player, TerrainScan, TerrainType, TileRun, TileWindow,
    TownNpc, WorldObject,
)


_BASE_URL = "http://127.0.0.1:17878"
_DEFAULT_URL = _BASE_URL + "/state"
_TIMEOUT_SEC = 0.1

_THREAT_OVERRIDES: dict[int, EnemyThreat] = {
    51:  EnemyThreat.DANGEROUS,  # Jungle Bat
    43:  EnemyThreat.DANGEROUS,  # Man Eater
    204: EnemyThreat.DANGEROUS,  # Spiked Jungle Slime
}


_NO_PROXY_HANDLER = urllib.request.ProxyHandler({})
_OPENER = urllib.request.build_opener(_NO_PROXY_HANDLER)


_PLAYER_W_TILES = 2
_PLAYER_H_TILES = 3
_SCAN_COLUMNS = 10


def _is_solid_at(tw: TileWindow, tx: int, ty: int) -> bool:
    t = tw.tile_at(tx, ty)
    return t is not None and t.solid and not t.platform


def _is_standable_at(tw: TileWindow, tx: int, ty: int) -> bool:
    t = tw.tile_at(tx, ty)
    if t is None:
        return False
    return t.solid


def _is_liquid_at(tw: TileWindow, tx: int, ty: int) -> int:
    t = tw.tile_at(tx, ty)
    if t is None:
        return 0
    if t.lava:
        return 2
    if t.water:
        return 1
    return 0


_TILE_PX = 16.0


def _jump_envelope(movement: MovementInfo, max_cols: int = 30) -> list[int]:
    h_speed = max(movement.max_run_speed, movement.acc_run_speed)
    if h_speed < 0.01:
        return [0] * max_cols
    js = movement.jump_speed
    grav = movement.gravity
    peak_t = js / max(grav, 0.01)
    peak_col = int(h_speed * peak_t / _TILE_PX)

    envelope = []
    for col in range(max_cols):
        if col <= peak_col:
            dy = 0
        else:
            fall_t = (col - peak_col) * _TILE_PX / h_speed
            dy = int(0.5 * grav * fall_t * fall_t / _TILE_PX)
        envelope.append(dy)
    return envelope


def _can_jump_over_pit(tw: TileWindow, pit_start_x: int, feet_y: int, sign: int,
                       movement: MovementInfo) -> bool:
    envelope = _jump_envelope(movement)
    for col, dy in enumerate(envelope):
        cx = pit_start_x + sign * col
        env_y = feet_y + dy
        for check_y in range(env_y, env_y + 10):
            if _is_standable_at(tw, cx, check_y):
                if check_y > feet_y + 2 and col == 0:
                    break
                return True
    return False


def _scan_terrain(tw: TileWindow, player: Player, movement: MovementInfo) -> TerrainScan:
    pcx = int((player.pos[0] + player.width / 2.0) / 16.0)
    feet_y = int((player.pos[1] + player.height) / 16.0)
    head_y = feet_y - _PLAYER_H_TILES

    sign = 1 if player.direction == "right" else -1
    start_x = pcx + sign * (_PLAYER_W_TILES // 2 + 1)

    for col_offset in range(_SCAN_COLUMNS):
        cx = start_x + sign * col_offset
        dist = col_offset + 1

        liquid = _is_liquid_at(tw, cx, feet_y)
        if liquid == 2:
            return TerrainScan(terrain_type=TerrainType.LAVA, distance_tiles=dist, depth_or_height=0)
        if liquid == 1:
            return TerrainScan(terrain_type=TerrainType.WATER, distance_tiles=dist, depth_or_height=0)

        body_blocked = any(_is_solid_at(tw, cx, y) for y in range(head_y, feet_y))
        if body_blocked:
            wall_h = 0
            for check_y in range(feet_y - 1, feet_y - 12, -1):
                if _is_solid_at(tw, cx, check_y):
                    wall_h += 1
                else:
                    break
            return TerrainScan(terrain_type=TerrainType.BLOCK_WALL, distance_tiles=dist, depth_or_height=wall_h)

        has_ground = False
        for dy in range(3):
            if _is_standable_at(tw, cx, feet_y + dy):
                has_ground = True
                break

        if not has_ground:
            pit_depth = 0
            for dy in range(40):
                if _is_standable_at(tw, cx, feet_y + dy):
                    pit_depth = dy
                    break
                pit_depth = dy + 1

            jumpable = _can_jump_over_pit(tw, cx, feet_y, sign, movement)
            if jumpable:
                return TerrainScan(terrain_type=TerrainType.FLAT, distance_tiles=dist, depth_or_height=pit_depth)
            return TerrainScan(terrain_type=TerrainType.PIT, distance_tiles=dist, depth_or_height=pit_depth)

    return TerrainScan(terrain_type=TerrainType.FLAT, distance_tiles=_SCAN_COLUMNS, depth_or_height=0)


class TerraBlindClient:
    def __init__(self, url: str = _DEFAULT_URL, timeout: float = _TIMEOUT_SEC) -> None:
        self._url = url
        self._timeout = timeout
        self._damage = DamageDetector()
        self._last_error_kind: str | None = None
        self._last_success_ts: float = 0.0

    def detect(self, frame) -> GameState:
        try:
            with _OPENER.open(self._url, timeout=self._timeout) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except urllib.error.URLError as e:
            self._note_error(f"urlerror:{type(e.reason).__name__}")
            return self._empty_state()
        except (TimeoutError, ConnectionError) as e:
            self._note_error(f"conn:{type(e).__name__}")
            return self._empty_state()
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            self._note_error(f"parse:{type(e).__name__}")
            return self._empty_state()

        self._last_success_ts = time.time()
        self._last_error_kind = None
        return self._build_game_state(payload)

    def _build_game_state(self, payload: dict) -> GameState:
        p = payload.get("player") or {}
        eq = payload.get("equipment") or {}
        cam_raw = payload.get("camera") or {}
        buffs_raw = payload.get("buffs") or []

        hp = int(p.get("hp", 0))
        max_hp = max(int(p.get("max_hp", 1)), 1)
        damage = self._damage.update(hp, max_hp, time.time())

        if "width" not in p or "height" not in p:
            raise ValueError("TerraBlind payload missing player.width/height — mod outdated?")
        if not cam_raw:
            raise ValueError("TerraBlind payload missing camera — mod outdated?")

        pos = p.get("pos") or {}
        vel = p.get("vel") or {}

        hotbar_raw = eq.get("hotbar") or []
        inv_raw = eq.get("inventory") or []
        coins_raw = eq.get("coins") or []
        ammo_raw = eq.get("ammo") or []

        inventory_slots: list[InventorySlot] = []
        slot_sources = [
            (hotbar_raw, 0, 10),
            (inv_raw, 10, 40),
            (coins_raw, 50, 4),
            (ammo_raw, 54, 4),
        ]
        for raw_list, base_idx, count in slot_sources:
            for i in range(count):
                raw = raw_list[i] if i < len(raw_list) and isinstance(raw_list[i], dict) else {}
                inventory_slots.append(InventorySlot(
                    slot_index=base_idx + i,
                    id=int(raw.get("id", 0)),
                    name=raw.get("name", ""),
                    stack=int(raw.get("stack", 0)),
                    damage=int(raw.get("damage", 0)),
                    pick=int(raw.get("pick", 0)),
                    axe=int(raw.get("axe", 0)),
                    hammer=int(raw.get("hammer", 0)),
                    create_tile=int(raw.get("create_tile", -1)),
                    consumable=bool(raw.get("consumable", False)),
                ))

        hotbar: list[Optional[str]] = [None] * 10
        for s in inventory_slots[:10]:
            if not s.is_empty:
                hotbar[s.slot_index] = s.name

        held = eq.get("held_item", {}) or {}
        equipped = held.get("name") or "none"

        inventory: dict[str, int] = {}
        for s in inventory_slots:
            if s.is_empty:
                continue
            inventory[s.name] = inventory.get(s.name, 0) + s.stack

        inventory_open = bool(eq.get("inventory_open", False))

        player = Player(
            hp=hp,
            max_hp=max_hp,
            mana=int(p.get("mana", 0)),
            max_mana=int(p.get("max_mana", 0)),
            pos=(float(pos.get("x", 0.0)), float(pos.get("y", 0.0))),
            width=float(p["width"]),
            height=float(p["height"]),
            velocity=(float(vel.get("x", 0.0)), float(vel.get("y", 0.0))),
            direction=str(p.get("direction", "right")),
            buffs=[str(b.get("name", "")) for b in buffs_raw if isinstance(b, dict)],
            took_damage=damage.took_damage,
            damage_amount=damage.damage_amount,
            danger_level=damage.danger_level,
            hp_trend=damage.hp_trend,
            selected_slot=int(eq.get("selected_slot", 0)),
            inventory_open=inventory_open,
        )
        cam_pos = cam_raw.get("screen_pos") or {}
        cam_size = cam_raw.get("screen_size") or {}
        camera = Camera(
            screen_pos=(float(cam_pos.get("x", 0.0)), float(cam_pos.get("y", 0.0))),
            screen_size=(int(cam_size.get("w", 0)), int(cam_size.get("h", 0))),
            zoom=float(cam_raw.get("zoom", 1.0)),
        )

        pcenter = player_center_world(player)

        enemies: list[Enemy] = []
        for e in payload.get("enemies") or []:
            if not isinstance(e, dict):
                continue
            epos_raw = e.get("pos") or {}
            epos = (float(epos_raw.get("x", 0.0)), float(epos_raw.get("y", 0.0)))
            evel_raw = e.get("vel") or {}
            dist = world_distance_tiles(pcenter, epos)
            hp_e = int(e.get("hp", 0))
            max_hp_e = max(int(e.get("max_hp", 1)), 1)
            boss = bool(e.get("boss", False))
            type_id = int(e.get("type", 0))
            threat = (
                EnemyThreat.BOSS if boss else
                _THREAT_OVERRIDES.get(type_id) or (
                    EnemyThreat.DANGEROUS if dist < 8 else
                    EnemyThreat.MEDIUM if dist < 20 else
                    EnemyThreat.WEAK
                )
            )
            enemies.append(Enemy(
                who=int(e.get("who", -1)),
                type_id=type_id,
                type=str(e.get("name", "")),
                pos=epos,
                velocity=(float(evel_raw.get("x", 0.0)), float(evel_raw.get("y", 0.0))),
                width=float(e.get("w", 0.0)),
                height=float(e.get("h", 0.0)),
                hp=hp_e,
                max_hp=max_hp_e,
                boss=boss,
                distance=dist,
                threat=threat,
            ))

        town_npcs: list[TownNpc] = []
        for n in payload.get("town_npcs") or []:
            if not isinstance(n, dict):
                continue
            npos_raw = n.get("pos") or {}
            town_npcs.append(TownNpc(
                who=int(n.get("who", -1)),
                type_id=int(n.get("type", 0)),
                name=str(n.get("name", "")),
                display_name=str(n.get("display_name", "")),
                pos=(float(npos_raw.get("x", 0.0)), float(npos_raw.get("y", 0.0))),
                homeless=bool(n.get("homeless", False)),
            ))

        tile_window = None
        tiles_raw = payload.get("tiles")
        if tiles_raw and isinstance(tiles_raw, dict):
            origin = tiles_raw.get("origin") or {}
            rows_raw = tiles_raw.get("rows") or []
            rows = [
                [TileRun(type=r[0], sflags=r[1], count=r[2]) for r in row if isinstance(r, list) and len(r) >= 3]
                for row in rows_raw if isinstance(row, list)
            ]
            tile_window = TileWindow(
                origin=(int(origin.get("x", 0)), int(origin.get("y", 0))),
                width=int(tiles_raw.get("w", 120)),
                height=int(tiles_raw.get("h", 80)),
                rows=rows,
            )

        objects: list[WorldObject] = []
        for o in payload.get("objects") or []:
            if not isinstance(o, dict):
                continue
            opos = o.get("pos") or {}
            wpos = (float(opos.get("x", 0.0)), float(opos.get("y", 0.0)))
            dist = world_distance_tiles(pcenter, wpos)
            objects.append(WorldObject(
                type=str(o.get("name", "")),
                pos=wpos,
                tile_pos=(int(o.get("tx", 0)), int(o.get("ty", 0))),
                distance=dist,
            ))

        dropped_items: list[DroppedItem] = []
        for di in payload.get("dropped_items") or []:
            if not isinstance(di, dict):
                continue
            dpos = di.get("pos") or {}
            dwpos = (float(dpos.get("x", 0.0)), float(dpos.get("y", 0.0)))
            dist = world_distance_tiles(pcenter, dwpos)
            dropped_items.append(DroppedItem(
                who=int(di.get("who", -1)),
                type_id=int(di.get("type", 0)),
                name=str(di.get("name", "")),
                stack=int(di.get("stack", 0)),
                pos=dwpos,
                distance=dist,
            ))

        mv_raw = payload.get("movement") or {}
        movement = MovementInfo(
            jump_speed=float(mv_raw.get("jump_speed", 5.01)),
            gravity=float(mv_raw.get("gravity", 0.4)),
            max_run_speed=float(mv_raw.get("max_run_speed", 3.0)),
            acc_run_speed=float(mv_raw.get("acc_run_speed", 0.0)),
            wing_time_max=int(mv_raw.get("wing_time_max", 0)),
            no_fall_dmg=bool(mv_raw.get("no_fall_dmg", False)),
            lava_immune=bool(mv_raw.get("lava_immune", False)),
            lava_time=int(mv_raw.get("lava_time", 0)),
            extra_jumps=int(mv_raw.get("extra_jumps", 0)),
        )

        terrain_ahead = TerrainType.FLAT
        terrain_scan = None
        if tile_window and tile_window.rows:
            terrain_scan = _scan_terrain(tile_window, player, movement)
            terrain_ahead = terrain_scan.terrain_type

        return GameState(
            player=player,
            camera=camera,
            enemies=enemies,
            town_npcs=town_npcs,
            hotbar=hotbar,
            equipped=equipped,
            inventory=inventory,
            inventory_slots=inventory_slots,
            tile_window=tile_window,
            objects=objects,
            dropped_items=dropped_items,
            movement=movement,
            terrain_ahead=terrain_ahead,
            terrain_scan=terrain_scan,
            chest_open=bool(eq.get("chest_open", False)),
            smart_cursor=bool(eq.get("smart_cursor", False)),
        )

    def _empty_state(self) -> GameState:
        return GameState(player=Player(hp=0, max_hp=1, pos=(0.0, 0.0)))

    def _note_error(self, kind: str) -> None:
        if self._last_error_kind != kind:
            self._last_error_kind = kind

    def loot_all(self) -> bool:
        try:
            with _OPENER.open(_BASE_URL + "/loot_all", timeout=self._timeout) as resp:
                return resp.status == 200
        except Exception:
            return False

    def reset(self) -> None:
        self._damage.reset()
