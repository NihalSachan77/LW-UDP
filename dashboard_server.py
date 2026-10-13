# -*- coding: utf-8 -*-
"""
NIHAL OFFICIAL - Web Dashboard Backend
Full support for Pause/Resume + Uptime + Match Tracking + Human Mode
"""
import asyncio
import json
import os
import time
from typing import Dict, List, Any, Optional
from aiohttp import web


# ==================== BOT STATE ====================
class BotState:
    def __init__(self):
        self.accounts: Dict[str, Dict[str, Any]] = {}
        self.logs: List[Dict[str, Any]] = []
        self.max_logs = 300
        self.total_matches = 0
        self.total_gained_exp = 0
        self.start_time = time.time()
        self.account_workers: Dict[str, asyncio.Task] = {}
        self.refresh_callbacks: Dict[str, Any] = {}
        self.account_credentials: Dict[str, Dict[str, Any]] = {}
        self._uptime_task: Optional[asyncio.Task] = None

    def log(self, message: str, level: str = "info", uid: Optional[str] = None):
        msg_lower = str(message).lower()
        category = "system"
        if level == "info":
            if any(k in msg_lower for k in ["match", "udp", "thunder", "sharma", "lone wolf", "battle", "searching", "loading", "br search", "lw search"]):
                category = "match"
            elif any(k in msg_lower for k in ["exp", "gained"]):
                category = "exp"
            elif any(k in msg_lower for k in ["login", "token", "auth", "cache", "session"]):
                category = "login"
            elif any(k in msg_lower for k in ["gateway", "tcp", "dns", "network", "connect"]):
                category = "network"
        entry = {
            "time": time.strftime("%H:%M:%S"),
            "level": level,
            "category": category,
            "message": str(message),
            "uid": uid,
        }
        self.logs.append(entry)
        if len(self.logs) > self.max_logs:
            self.logs.pop(0)

    def register_account(self, uid: str, nickname: str, region: str, level: int, exp: int, likes: int = 0):
        uid_str = str(uid)
        lvl_val = max(1, int(level or 1))
        if uid_str not in self.accounts:
            self.accounts[uid_str] = {
                "uid": uid_str,
                "nickname": nickname or f"Player_{uid_str[:6]}",
                "region": region or "IND",
                "level": lvl_val,
                "initial_exp": exp,
                "current_exp": exp,
                "gained_exp": 0,
                "likes": likes or 0,
                "mode": "LONE_WOLF",
                "mode_manual": True,
                "status": "ONLINE",
                "matches_played": 0,
                "matches_completed": 0,
                "matches_failed": 0,
                "active_matches": 0,
                "uptime_seconds": 0,
                "is_paused": False,
                "last_match_time": None,
                "last_updated": time.strftime("%H:%M:%S"),
            }
        else:
            acc = self.accounts[uid_str]
            if nickname:
                acc["nickname"] = nickname
            if region:
                acc["region"] = region
            if level:
                acc["level"] = lvl_val
            acc["current_exp"] = exp
            acc["gained_exp"] = max(0, exp - acc["initial_exp"])
            acc["likes"] = likes
            acc["status"] = "ONLINE" if not acc.get("is_paused") else "PAUSED"
            acc["last_updated"] = time.strftime("%H:%M:%S")
        self.recalc_totals()

    def update_exp(self, uid: str, current_exp: int, level: Optional[int] = None):
        uid_str = str(uid)
        if uid_str not in self.accounts:
            return
        acc = self.accounts[uid_str]
        old_exp = acc.get("current_exp", 0)
        acc["current_exp"] = current_exp
        if level is not None and level > 0:
            acc["level"] = int(level)
        acc["gained_exp"] = max(0, current_exp - acc.get("initial_exp", 0))
        acc["last_updated"] = time.strftime("%H:%M:%S")
        diff = current_exp - old_exp
        if diff > 0:
            self.log(
                f"+{diff} EXP | {acc.get('nickname', uid_str)} now Lv{acc.get('level', 1)} | Total: +{acc['gained_exp']}",
                "success",
                uid_str,
            )
        self.recalc_totals()

    def get_account_level(self, uid: str) -> int:
        acc = self.accounts.get(str(uid))
        return int(acc.get("level", 1) or 1) if acc else 1

    def get_account_mode(self, uid: str) -> str:
        acc = self.accounts.get(str(uid))
        if not acc:
            return "LONE_WOLF"
        return str(acc.get("mode", "LONE_WOLF") or "LONE_WOLF").upper()

    def set_account_mode(self, uid: str, mode: str):
        uid_str = str(uid)
        mode = str(mode or "").upper().replace("-", "_").replace(" ", "_")
        if mode in ("LW", "LONEWOLF", "LONE_WOLF"):
            mode = "LONE_WOLF"
        else:
            return False, "Only Lone Wolf mode is supported (BR disabled)"
        acc = self.accounts.get(uid_str)
        if not acc:
            return False, "Account not found"
        acc["mode"] = mode
        acc["mode_manual"] = True
        acc["last_updated"] = time.strftime("%H:%M:%S")
        self.log(f"Mode locked to {mode}", "info", uid_str)
        return True, mode

    def update_status(self, uid: str, status: str, active_matches: Optional[int] = None):
        uid_str = str(uid)
        if uid_str not in self.accounts:
            return
        if self.accounts[uid_str].get("is_paused") and status not in ("PAUSED", "OFFLINE"):
            status = "PAUSED"
        self.accounts[uid_str]["status"] = status
        if active_matches is not None:
            self.accounts[uid_str]["active_matches"] = active_matches
        self.accounts[uid_str]["last_updated"] = time.strftime("%H:%M:%S")

    def increment_match(self, uid: str):
        uid_str = str(uid)
        self.total_matches += 1
        if uid_str in self.accounts:
            acc = self.accounts[uid_str]
            acc["matches_played"] = acc.get("matches_played", 0) + 1
            acc["matches_completed"] = acc.get("matches_completed", 0) + 1
            acc["last_match_time"] = time.strftime("%H:%M:%S")
            acc["last_updated"] = time.strftime("%H:%M:%S")
            self.log(
                f"Match #{acc['matches_played']} completed | {acc.get('nickname', uid_str)}",
                "success",
                uid_str,
            )

    def match_failed(self, uid: str):
        uid_str = str(uid)
        if uid_str in self.accounts:
            acc = self.accounts[uid_str]
            acc["matches_failed"] = acc.get("matches_failed", 0) + 1
            acc["last_updated"] = time.strftime("%H:%M:%S")

    def recalc_totals(self):
        self.total_gained_exp = sum(acc.get("gained_exp", 0) for acc in self.accounts.values())

    def is_paused(self, uid: str) -> bool:
        acc = self.accounts.get(str(uid))
        if not acc:
            return False
        return bool(acc.get("is_paused", False) or acc.get("status") == "PAUSED")

    def set_paused(self, uid: str, paused: bool) -> bool:
        uid_str = str(uid)
        if uid_str not in self.accounts:
            return False
        self.accounts[uid_str]["is_paused"] = bool(paused)
        self.accounts[uid_str]["status"] = "PAUSED" if paused else "ONLINE"
        self.accounts[uid_str]["last_updated"] = time.strftime("%H:%M:%S")
        self.log(
            f"Node {'paused' if paused else 'resumed'}",
            "warning" if paused else "success",
            uid_str,
        )
        return True

    def all_paused(self) -> bool:
        if not self.accounts:
            return False
        return all(a.get("is_paused", False) or a.get("status") == "PAUSED" for a in self.accounts.values())

    def pause_all(self, paused: bool = True) -> int:
        count = 0
        for uid in list(self.accounts.keys()):
            if self.set_paused(uid, paused):
                count += 1
        return count

    async def uptime_ticker(self):
        while True:
            try:
                await asyncio.sleep(1)
                for uid, acc in list(self.accounts.items()):
                    if acc.get("status") in ("ONLINE", "IN_MATCH", "SEARCHING", "CONNECTING", "WAITING_LV3") and not acc.get("is_paused"):
                        acc["uptime_seconds"] = acc.get("uptime_seconds", 0) + 1
            except asyncio.CancelledError:
                break
            except Exception:
                pass

    def start_uptime_tracker(self):
        try:
            loop = asyncio.get_event_loop()
            if self._uptime_task is None or self._uptime_task.done():
                self._uptime_task = loop.create_task(self.uptime_ticker())
        except Exception:
            pass


bot_state = BotState()


# ==================== HTTP HANDLERS ====================
TEMPLATE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates", "index.html")


async def handle_index(request: web.Request) -> web.Response:
    if os.path.exists(TEMPLATE_PATH):
        with open(TEMPLATE_PATH, "r", encoding="utf-8") as f:
            content = f.read()
    else:
        content = "<h1>templates/index.html not found!</h1>"
    return web.Response(text=content, content_type="text/html", charset="utf-8")


async def handle_get_stats(request: web.Request) -> web.Response:
    accounts_data = list(bot_state.accounts.values())
    accounts_data.sort(key=lambda x: x.get("gained_exp", 0), reverse=True)
    uptime = max(1, int(time.time() - bot_state.start_time))
    uptime_hours = max(0.016, uptime / 3600.0)
    exp_per_hour = int(bot_state.total_gained_exp / uptime_hours) if uptime_hours > 0 else 0
    total_active = sum(int(a.get("active_matches", 0) or 0) for a in accounts_data)
    return web.json_response({
        "total_accounts": len(bot_state.accounts),
        "total_matches": bot_state.total_matches,
        "total_matches_started": bot_state.total_matches,
        "total_gained_exp": bot_state.total_gained_exp,
        "total_active_matches": total_active,
        "exp_per_hour": exp_per_hour,
        "accounts": accounts_data,
        "logs": bot_state.logs[-100:],
        "uptime": uptime,
    })


async def handle_add_account(request: web.Request) -> web.Response:
    try:
        data = await request.json()
        accounts_file = "accounts.json"
        existing = []
        if os.path.exists(accounts_file):
            try:
                with open(accounts_file, "r", encoding="utf-8") as f:
                    existing = json.load(f)
            except Exception:
                existing = []
        if "uid" in data and "password" in data:
            uid = str(data["uid"]).strip()
            pwd = str(data["password"]).strip()
            if not uid or not pwd:
                return web.json_response({"status": "error", "error": "UID and Password required"})
            existing = [acc for acc in existing if str(acc.get("uid")) != uid]
            existing.append({"uid": uid, "password": pwd})
        elif "token" in data:
            token = str(data["token"]).strip()
            if not token:
                return web.json_response({"status": "error", "error": "Token required"})
            existing = [acc for acc in existing if acc.get("token") != token]
            existing.append({"token": token})
        else:
            return web.json_response({"status": "error", "error": "Invalid payload"})
        with open(accounts_file, "w", encoding="utf-8") as f:
            json.dump(existing, f, indent=2)
        bot_state.log(f"New account added: {data.get('uid') or 'Token'}", "success")
        if "on_account_added" in bot_state.refresh_callbacks:
            asyncio.create_task(bot_state.refresh_callbacks["on_account_added"](data))
        return web.json_response({"status": "ok"})
    except Exception as e:
        return web.json_response({"status": "error", "error": str(e)})


async def handle_delete_account(request: web.Request) -> web.Response:
    try:
        data = await request.json()
        uid = str(data.get("uid", "")).strip()
        token = str(data.get("token", "")).strip()
        accounts_file = "accounts.json"
        if os.path.exists(accounts_file):
            with open(accounts_file, "r", encoding="utf-8") as f:
                existing = json.load(f)
            if token:
                existing = [acc for acc in existing if str(acc.get("token", "")).strip() != token]
            elif uid:
                existing = [acc for acc in existing if str(acc.get("uid", "")).strip() != uid]
            with open(accounts_file, "w", encoding="utf-8") as f:
                json.dump(existing, f, indent=2)
        worker_keys = []
        if uid:
            worker_keys.append(uid)
        if token:
            worker_keys.append(token[:10])
        for key in worker_keys:
            worker = bot_state.account_workers.get(key)
            if worker:
                if not worker.done():
                    worker.cancel()
                bot_state.account_workers.pop(key, None)
        if uid and uid in bot_state.accounts:
            del bot_state.accounts[uid]
        bot_state.log(f"Account {uid or token[:10] or 'unknown'} removed.", "warning", uid or None)
        return web.json_response({"status": "ok"})
    except Exception as e:
        return web.json_response({"status": "error", "error": str(e)})


async def handle_refresh_account(request: web.Request) -> web.Response:
    try:
        data = await request.json()
        uid = str(data.get("uid")).strip()
        if "on_refresh_account" in bot_state.refresh_callbacks:
            asyncio.create_task(bot_state.refresh_callbacks["on_refresh_account"](uid))
        return web.json_response({"status": "ok"})
    except Exception as e:
        return web.json_response({"status": "error", "error": str(e)})


async def handle_mode_switch(request: web.Request) -> web.Response:
    try:
        data = await request.json()
        uid = str(data.get("uid", "")).strip()
        mode = str(data.get("mode", "")).strip()
        ok, result = bot_state.set_account_mode(uid, mode)
        if not ok:
            return web.json_response({"status": "error", "error": result}, status=400)
        return web.json_response({
            "status": "ok",
            "uid": uid,
            "mode": result,
            "level": bot_state.get_account_level(uid),
        })
    except Exception as e:
        return web.json_response({"status": "error", "error": str(e)}, status=400)


async def handle_pause(request: web.Request) -> web.Response:
    try:
        data = await request.json()
        uid = str(data.get("uid", "")).strip()
        if not uid:
            return web.json_response({"status": "error", "error": "uid required"}, status=400)
        if uid not in bot_state.accounts:
            return web.json_response({"status": "error", "error": "account not found"}, status=404)
        current = bot_state.is_paused(uid)
        new_state = not current
        bot_state.set_paused(uid, new_state)
        return web.json_response({"status": "ok", "is_paused": new_state, "uid": uid})
    except Exception as e:
        return web.json_response({"status": "error", "error": str(e)}, status=400)


async def handle_pause_all(request: web.Request) -> web.Response:
    try:
        currently_all_paused = bot_state.all_paused()
        new_state = not currently_all_paused
        count = bot_state.pause_all(new_state)
        return web.json_response({"status": "ok", "all_paused": new_state, "count": count})
    except Exception as e:
        return web.json_response({"status": "error", "error": str(e)}, status=400)


async def handle_restart_account(request: web.Request) -> web.Response:
    try:
        data = await request.json()
        uid = str(data.get("uid", "")).strip()
        if not uid:
            return web.json_response({"status": "error", "error": "uid required"}, status=400)
        worker = bot_state.account_workers.get(uid)
        if worker and not worker.done():
            worker.cancel()
        bot_state.log(f"Restarting worker for {uid}", "warning", uid)
        return web.json_response({"status": "ok"})
    except Exception as e:
        return web.json_response({"status": "error", "error": str(e)}, status=400)


async def handle_clear_logs(request: web.Request) -> web.Response:
    try:
        bot_state.logs.clear()
        return web.json_response({"status": "ok"})
    except Exception as e:
        return web.json_response({"status": "error", "error": str(e)}, status=400)


# ==================== DASHBOARD START ====================
async def start_web_dashboard(host: str = "0.0.0.0", port: int = 20333):
    app = web.Application()
    app.router.add_get("/", handle_index)
    app.router.add_get("/api/stats", handle_get_stats)
    app.router.add_post("/api/account/add", handle_add_account)
    app.router.add_post("/api/account/delete", handle_delete_account)
    app.router.add_post("/api/account/refresh", handle_refresh_account)
    app.router.add_post("/api/account/restart", handle_restart_account)
    app.router.add_post("/api/account/mode", handle_mode_switch)
    app.router.add_post("/api/account/pause", handle_pause)
    app.router.add_post("/api/account/pause_all", handle_pause_all)
    app.router.add_post("/api/logs/clear", handle_clear_logs)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host, port)
    await site.start()

    bot_state.start_uptime_tracker()

    print(f"\033[92m[+] Web Dashboard running on http://localhost:{port}\033[0m")