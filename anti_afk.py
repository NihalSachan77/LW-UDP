# -*- coding: utf-8 -*-
import asyncio
import random
import time
import struct

PING_INTERVAL = 1.5
INPUT_INTERVAL = 8.0
ACTION_INTERVAL = 25.0

PING_KEYS = [0x66, 0x6D, 0x69, 0x6C, 0x6B, 0x6E, 0x6F, 0x70, 0x71, 0x72]

MOVEMENT_PACKETS = [
    bytes.fromhex("0f0101000000000000"),
    bytes.fromhex("0f0102000000000000"),
    bytes.fromhex("0f0103000000000000"),
    bytes.fromhex("0f0104000000000000"),
    bytes.fromhex("0f0105000000000000"),
    bytes.fromhex("0f0106000000000000"),
]

ACTION_PACKETS = [
    bytes.fromhex("1101010000000000"),
    bytes.fromhex("1101020000000000"),
    bytes.fromhex("1101030000000000"),
    bytes.fromhex("1101040000000000"),
]


class AntiAFKManager:
    def __init__(self, sock, server_addr, udp_key_bytes, match_code,
                 build_packet_fn, layouts_fn, logger=None):
        self.sock = sock
        self.server_addr = server_addr
        self.udp_key_bytes = udp_key_bytes
        self.match_code = match_code
        self.build_packet = build_packet_fn
        self.get_layouts = layouts_fn
        self.log = logger or (lambda x: None)
        self.loop = None
        self._stop_event = asyncio.Event()
        self._tasks = []
        self._ping_count = 0
        self._input_count = 0
        self._action_count = 0
        self._last_server_response = time.time()

    async def start(self):
        self.loop = asyncio.get_event_loop()
        self._stop_event.clear()
        self._tasks = [
            asyncio.create_task(self._ping_loop()),
            asyncio.create_task(self._input_loop()),
            asyncio.create_task(self._action_loop()),
            asyncio.create_task(self._watchdog_loop()),
        ]
        self.log("[ANTI-AFK] Started")

    async def stop(self):
        self._stop_event.set()
        for t in self._tasks:
            t.cancel()
            try:
                await t
            except asyncio.CancelledError:
                pass

    def note_server_response(self):
        self._last_server_response = time.time()

    async def _ping_loop(self):
        i = 0
        while not self._stop_event.is_set():
            try:
                pk = PING_KEYS[i % len(PING_KEYS)]
                counter = int(time.time() * 1000) & 0xFFFFFFFF
                nr = (await self.get_layouts(self.match_code))[1]
                pkt = await self.build_packet(
                    pk, nr, 0, 3, None, 0,
                    struct.pack("<I", counter) + b"\x00\x00\x00",
                    self.udp_key_bytes, encrypted=False
                )
                await self.loop.sock_sendto(self.sock, pkt, self.server_addr)
                self._ping_count += 1
                i += 1
            except Exception:
                pass
            jitter = random.uniform(-0.3, 0.3)
            try:
                await asyncio.wait_for(
                    self._stop_event.wait(),
                    timeout=max(0.5, PING_INTERVAL + jitter)
                )
            except asyncio.TimeoutError:
                pass

    async def _input_loop(self):
        while not self._stop_event.is_set():
            try:
                await asyncio.sleep(INPUT_INTERVAL + random.uniform(-1.0, 1.0))
                if self._stop_event.is_set():
                    break
                pkt = random.choice(MOVEMENT_PACKETS)
                await self.loop.sock_sendto(self.sock, pkt, self.server_addr)
                self._input_count += 1
            except Exception:
                pass

    async def _action_loop(self):
        while not self._stop_event.is_set():
            try:
                await asyncio.sleep(ACTION_INTERVAL + random.uniform(-3.0, 3.0))
                if self._stop_event.is_set():
                    break
                pkt = random.choice(ACTION_PACKETS)
                await self.loop.sock_sendto(self.sock, pkt, self.server_addr)
                self._action_count += 1
            except Exception:
                pass

    async def _watchdog_loop(self):
        while not self._stop_event.is_set():
            try:
                await asyncio.sleep(5.0)
                idle = time.time() - self._last_server_response
                if idle > 15.0:
                    self.log(f"[ANTI-AFK] Server silent {int(idle)}s")
                    self._last_server_response = time.time()
            except Exception:
                pass
